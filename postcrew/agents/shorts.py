"""The YouTube crew: the owner's Shorts factory (~/Youtube/shorts-factory), used as it is.

  1. Script Writer: Claude Code, started inside the factory's folder, so it follows the factory's CLAUDE.md and its
     `explainer-short-style` skill. It writes episodes/<slug>/script.json and youtube.json for the day's topic (it renders nothing).
  2. Render: `npm run make -- episodes/<slug>`: Kokoro voice -> HyperFrames (or Remotion) -> FFmpeg, into out/<slug>-<engine>.mp4.
  3. The Publisher queues it like any other post (approval, schedule, upload with postcrew's YouTube connection).

Nothing in the factory is changed by postcrew. Where it lives: video.factory_path in the YouTube settings, else $POSTCREW_SHORTS_FACTORY,
else ~/Youtube/shorts-factory.
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .base import Agent, AgentError
from ..llm import agent_settings

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
WRITER_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "Skill", "Bash(npm run variety:*)", "Bash(python3 algo/*)", "Bash(python3 -I algo/*)"]
SKILL = ".claude/skills/explainer-short-style"
# Said to Claude on every run, so a scheduled video always follows the skill as it is NOW (changed from the Studio's Factory chat or by hand):
# the skill is read from disk at the start of each run, never remembered from an earlier one.
SKILL_RULE = (f"BEFORE writing anything, read the current skill from disk: {SKILL}/SKILL.md in full (including its Owner rules log at the "
              f"bottom), then every file in {SKILL}/references/ that SKILL.md points to for this kind of video, and CLAUDE.md. These files "
              f"change often: their newest rules win over anything in the example episodes. "
              f"Every video must differ from the recent ones (the owner will monetise the channel; YouTube refuses template look-alikes): "
              f"run `npm run variety` in shorts-factory/ first and follow {SKILL}/references/variety.md (shape, hook, voice, speed, scene "
              f"order, opening, title, sign-off), then run `npm run variety -- episodes/<slug>` and fix the script until it prints ok. "
              f"Owner rules (2026-11-12): a Short is AT MOST 60 SECONDS, at most 160 words of narration (count them), one idea; and it is a "
              f"VISUAL explainer of what the thing is and how it works, never a coding build: code scenes only in an algorithm problem, "
              f"which sets \"kind\": \"algorithm\" in script.json. Two looks (owner, 2026-11-12): an algorithm problem keeps the Signal look "
              f"(code and traces); EVERY OTHER Short is a Story video (\"style\": \"story\", \"kind\": \"explainer\"): the fixed cast acts out an "
              f"everyday story in a background that fits it, and a map scene pairs the story with the real tech. Read "
              f"{SKILL}/references/story-style.md first and follow it exactly. Only the narrator speaks; characters talk in short tooltips.")


def skill_version(root):
    """{file: modified time} of the factory's CLAUDE.md and skill, and a short fingerprint of them: which rules a video was made with."""
    import hashlib
    base = Path(root).parent
    files = [base / "CLAUDE.md"] + sorted((base / SKILL).rglob("*.md"))
    h = hashlib.sha1()
    for f in files:
        if f.exists():
            h.update(f.read_bytes())
    newest = max((f.stat().st_mtime for f in files if f.exists()), default=0)
    from datetime import datetime, timezone
    return {"fingerprint": h.hexdigest()[:10],
            "changed": datetime.fromtimestamp(newest, timezone.utc).isoformat(timespec="seconds") if newest else ""}


def factory_dir(cfg):
    p = (cfg.get("video") or {}).get("factory_path") or os.environ.get("POSTCREW_SHORTS_FACTORY") or "~/Youtube/shorts-factory"
    return Path(p).expanduser()


def slug_for(day, topic):
    words = re.sub(r"[^a-z0-9]+", "-", str(topic).lower()).strip("-")[:48].strip("-") or "short"
    return f"{day.isoformat()}-{words}"


def _recent(ctx, n=12):
    titles = [str((p.get("youtube") or {}).get("title") or p.get("topic") or "") for p in ctx.ws.history()
              if p.get("platform") == "youtube"]
    return [t for t in titles if t][-n:]


# a Story video must be a story (owner, 2026-11-12; the same check as the factory's pipeline/storycheck.mjs)
STORY_MOVES = {"enter", "walk", "carry", "jump"}
TECHY = {"computer", "computers", "model", "models", "algorithm", "data", "database", "server", "servers", "api", "apis", "code", "network", "vector",
         "vectors", "software", "app", "apps", "ai", "internet", "website", "cloud", "cache", "token", "query", "bytes", "program", "cpu", "gpu"}
COMMON = {"similar", "close", "nearest", "search", "numbers", "number", "list", "meaning", "first", "every", "right", "point"}


def story_problems(script):
    """What makes a "style": "story" script a lecture instead of a story. [] when it is a story."""
    if script.get("style") != "story":
        return []
    out, scenes = [], script.get("scenes") or []
    story = [s for s in scenes if s.get("type") == "story"]
    if len(str((script.get("analogy") or {}).get("world") or "").split()) < 8:
        out.append('"analogy": {"world": "…"} is missing: write the everyday story in one sentence first (who does what, where), with no tech '
                   "words; every story scene acts it out")
    if not any(s.get("type") == "map" for s in scenes):
        out.append('a Story video ends its story with a "map" scene that pairs each part of the story with the real tech term')
    terms = set()
    for s in scenes:
        for pr in s.get("pairs") or []:
            t = str(pr.get("tech") or "").lower().strip()
            if t:
                terms.add(t)
                head = t.split()[0].rstrip("s")
                if len(head) >= 6 and head not in COMMON:
                    terms.add(head)
    for i, s in enumerate(scenes):
        if s.get("type") != "story":
            continue
        text = str(s.get("text") or "").lower()
        techy = sorted(w for w in TECHY if re.search(rf"\b{re.escape(w)}\b", text))
        if techy:
            out.append(f'scene {i} is in the computer world ("{", ".join(techy)}"): story scenes happen in the everyday world of the analogy; '
                       f"computers are named only in the map scene")
        hit = sorted(t for t in terms if re.search(rf"\b{re.escape(t)}", text))
        if hit:
            out.append(f'scene {i} says "{", ".join(hit)}" before the map: the tech is named only in the map scene')
    moving = [s for s in story if any(b.get("do") in STORY_MOVES and b.get("who") for b in s.get("beats") or [])]
    if story and len(moving) < max(1, len(story) - 1):
        out.append(f"the cast only stands and talks: someone moves in {len(moving)} of {len(story)} story scenes. Make them act the story "
                   f"(enter, walk, carry a thing to its place, jump), not present a diagram")
    return out


SHORT_MAX_WORDS = 160   # the channel voice reads ~190 words a minute with the scene gaps: 160 words is about 52 s (factory pipeline/rules.mjs)
CODE_SCENES = {"code", "codeviz", "code-zoom", "run", "terminal", "editor"}


def _said(sc):
    return str(sc.get("text") or sc.get("say") or sc.get("narration") or sc.get("voice") or "")


class ShortsWriter(Agent):
    id = "writer"
    title = "Script Writer"
    name = "Claude"
    role = "Writes the Short's script.json and youtube.json in the Shorts factory, following its explainer-short-style skill."

    def run(self, ctx, guidance):
        root = factory_dir(ctx.cfg)
        if not (root / "package.json").exists():
            raise AgentError(f"the Shorts factory is not at {root}: set its folder in Settings (YouTube > video > factory path)", fatal=True)
        topic = ctx.outputs.get("topic") or {}
        subject = topic.get("topic") or ""
        slug = slug_for(ctx.day, subject or ctx.cat["label"])
        ep = root / "episodes" / slug
        if ep.exists() and not (ctx.options or {}).get("keep_episode"):
            shutil.rmtree(ep / "build", ignore_errors=True)
            for f in ("script.json", "youtube.json"):
                (ep / f).unlink(missing_ok=True)
        prompt = "\n".join(x for x in [
            f"Make the next YouTube Short for this channel, as episode `episodes/{slug}/` of shorts-factory.",
            f"Topic: {subject}" if subject else f"Pick a fresh topic for the category below (not one of the recent videos).",
            f"Angle: {topic.get('angle')}" if topic.get("angle") and topic.get("angle") != subject else "",
            f"Category: {ctx.cat['label']}: {ctx.cat.get('brief', '')}",
            ("Owner's plan for this video:\n" + json.dumps(topic["owner_plan"], ensure_ascii=False, indent=1)) if topic.get("owner_plan") else "",
            ("Recent videos (do not repeat): " + "; ".join(_recent(ctx))) if _recent(ctx) else "",
            "",
            SKILL_RULE,
            "Follow CLAUDE.md and the explainer-short-style skill exactly, as for any video in this workspace. Use the existing episodes as",
            "examples of the files. Write ONLY these two files:",
            f"  shorts-factory/episodes/{slug}/script.json   (the scenes and narration)",
            f"  shorts-factory/episodes/{slug}/youtube.json  (title, description, tags, privacyStatus \"private\"; video \"../../out/{slug}-hyperframes.mp4\", captions \"../../out/{slug}.srt\")",
            "Any per-episode assets go in that episode folder. Do NOT render, do NOT run npm, do NOT upload, and do NOT change the skill,",
            "the templates or the pipeline. When the two files are written, answer with one line: DONE.",
            ("\nThe owner's notes on the last attempt (fix these):\n- " + "\n- ".join(guidance)) if guidance else "",
        ] if x is not None)
        s = agent_settings(ctx.cfg, self.id)
        binary = ctx.cfg["llm"].get("claude_path") or "claude"
        cmd = [binary, "-p", "--output-format", "json", "--no-session-persistence", "--model", str(s.get("model", "sonnet")),
               "--max-budget-usd", str(max(float(s.get("max_budget_usd", 1.0)), 2.0)),
               "--permission-mode", "acceptEdits", "--allowedTools", ",".join(WRITER_TOOLS), "--tools", ",".join(WRITER_TOOLS)]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=str(root.parent),
                               timeout=max(int(s.get("timeout_s", 600)), 1200))
        except FileNotFoundError:
            raise AgentError(f"Claude Code CLI '{binary}' not found", fatal=True)
        except subprocess.TimeoutExpired:
            raise AgentError("the Script Writer did not finish within 20 minutes")
        try:
            out = json.loads(r.stdout)
        except ValueError:
            raise AgentError(f"claude exited {r.returncode}: {(r.stderr or r.stdout or '').strip()[-400:]}")
        cost = float(out.get("total_cost_usd") or 0)
        ctx.run.add_cost(self.id, cost)
        ctx.run.event(self.id, "llm", f"Claude Code wrote the episode in {time.time() - t0:.0f}s (${cost:.4f}, {out.get('num_turns')} turns)",
                      {"cost_usd": cost, "turns": out.get("num_turns")})
        if out.get("is_error") or out.get("subtype") != "success":
            text = str(out.get("result") or out.get("subtype"))[:300]
            raise AgentError(f"Claude Code stopped: {text}", fatal="limit" in text.lower())
        try:
            script = json.loads((ep / "script.json").read_text())
            meta = json.loads((ep / "youtube.json").read_text())
        except (OSError, ValueError) as e:
            raise AgentError(f"the episode files were not written correctly: {e}")
        return {"slug": slug, "episode": str(ep), "skill": skill_version(root), "title": meta.get("title", ""), "description": meta.get("description", ""),
                "tags": meta.get("tags") or [], "scene_count": len(script.get("scenes") or []),
                "narration": " ".join(_said(sc) for sc in script.get("scenes") or [])[:4000],
                "words": sum(len(_said(sc).split()) for sc in script.get("scenes") or []), "long": script.get("format") == "long",
                "kind": script.get("kind") or "", "style": script.get("style") or "", "code_scenes": sum(1 for sc in script.get("scenes") or [] if sc.get("type") in CODE_SCENES),
                "story_problems": story_problems(script)}

    def validate(self, ctx, out):
        p = []
        if not out.get("title"):
            p.append("youtube.json has no title")
        if not out.get("scene_count"):
            p.append("script.json has no scenes")
        if not out.get("long") and out.get("words", 0) > SHORT_MAX_WORDS:   # the owner's 60-second limit (2026-11-12), before any render
            p.append(f"the narration has {out['words']} words: a Short is at most 60 seconds, {SHORT_MAX_WORDS} words. Cut whole scenes "
                     f"(one idea per Short) and write script.json again")
        if not out.get("long") and out.get("kind") != "algorithm" and out.get("style") != "story":
            p.append("an explainer Short is a Story video (owner, 2026-11-12): set \"style\": \"story\" and tell it with the cast in a fitting "
                     "background, as references/story-style.md says. Only algorithm problems (\"kind\": \"algorithm\") keep the Signal look")
        p += out.get("story_problems") or []
        if out.get("code_scenes") and out.get("kind") != "algorithm":
            p.append(f"{out['code_scenes']} code scene(s) in a video that is not an algorithm problem: the channel makes visual explainers "
                     f"(owner, 2026-11-12). Replace them with diagram, flow or define scenes")
        return p

    def summary(self, out):
        return f"{out['title']} ({out['scene_count']} scenes, skill {(out.get('skill') or {}).get('fingerprint', '?')})"


class ShortsRender(Agent):
    id = "media"
    title = "Render"
    name = "Shorts factory"
    role = "Kokoro voice, HyperFrames/Remotion pictures and the FFmpeg finish: npm run make."
    uses_llm = False

    def run(self, ctx, guidance):
        root = factory_dir(ctx.cfg)
        w = ctx.outputs["writer"]
        t0 = time.time()
        try:
            r = subprocess.run(["npm", "run", "make", "--", f"episodes/{w['slug']}"], cwd=str(root), capture_output=True, text=True,
                               timeout=3600)
        except subprocess.TimeoutExpired:
            raise AgentError("the render did not finish within an hour")
        (ctx.run.dir / "render.log").write_text((r.stdout or "") + "\n" + (r.stderr or ""))
        if r.returncode:
            tail = re.sub(r"\x1b\[[0-9;]*m", "", (r.stderr or r.stdout or ""))[-600:]
            raise AgentError(f"npm run make failed (exit {r.returncode}): {tail}")
        engine = next((e for e in ("hyperframes", "remotion") if (root / "out" / f"{w['slug']}-{e}.mp4").exists()), None)
        if not engine:
            raise AgentError("the render finished but out/ has no video for this episode")
        video = root / "out" / f"{w['slug']}-{engine}.mp4"
        try:
            secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                                        capture_output=True, text=True, timeout=60).stdout.strip())
        except (ValueError, OSError):
            secs = 0.0
        thumb = video.with_suffix(".jpg")
        srt = root / "out" / f"{w['slug']}.srt"
        return {"path": str(video), "thumbnail_path": str(thumb) if thumb.exists() else "", "captions_path": str(srt) if srt.exists() else "",
                "seconds": round(secs, 1), "engine": engine, "render_s": round(time.time() - t0)}

    def summary(self, out):
        return f"{out['seconds']:.0f} s video ({out['engine']}, rendered in {out['render_s']} s)"
