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
from .. import factory_styles
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
              f"Owner rules (2026-11-15): a Short runs 50 TO 90 SECONDS, 150-260 words of narration (count them), one idea explained properly "
              f"(what it is, why it matters, how it works, an example); and it is a "
              f"VISUAL explainer of what the thing is and how it works, never a coding build: code scenes only in an algorithm problem, "
              f"which sets \"kind\": \"algorithm\" in script.json. The look follows the LOOKS line below: Signal (blue) is the default; the Story "
              f"look (the cast, {SKILL}/references/story-style.md) is used only when it is ticked, and then only for explainer Shorts.")


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


# 3D look (video-engine): the channel voice (dip_puck) reads ~2.9 words/s, and each beat adds ~0.6 s of breathing room
SHORT_MIN_WORDS_3D, SHORT_MAX_WORDS_3D = 110, 190   # owner, 2026-11-15: a Short runs 50-90 s; video-engine speaks ~2.45 words/s with its beat gaps, + the ~9 s outro
SHORT_MIN_WORDS_ISO, SHORT_MAX_WORDS_ISO = 150, 250   # Isometric Pastel Shorts, 50-90 s (owner, 2026-11-15): ~3.2 words/s with the beat gaps, + the ~5 s outro


def iso_check(root, ep):
    """The Isometric Pastel storyboard check (free: key frames in headless Chrome, no voice, no LLM): its list of problems."""
    (Path(ep) / "build-iso" / "check.json").unlink(missing_ok=True)   # never read an old run's problems
    r = subprocess.run(["node", str(Path(root) / "pipeline" / "make-iso.mjs"), str(ep), "--check"], cwd=str(root), capture_output=True, text=True,
                       timeout=300)
    if r.returncode == 0:
        return []
    try:
        got = json.loads((Path(ep) / "build-iso" / "check.json").read_text()).get("problems") or []
    except (OSError, ValueError):
        got = []
    return got or [((r.stderr or r.stdout or "").strip().splitlines() or [f"the check failed (exit {r.returncode})"])[-1]]

WORDS_PER_SECOND_3D = 2.5  # long videos: about 90% of the target length after beat pauses (measured 2026-11-14)


def engine_dir(cfg):
    """video-engine (render-only 3D engine): video.engine_path in YouTube settings, else $POSTCREW_VIDEO_ENGINE, else ~/video-engine."""
    p = (cfg.get("video") or {}).get("engine_path") or os.environ.get("POSTCREW_VIDEO_ENGINE") or "~/video-engine"
    return Path(p).expanduser()


def compile_storyboard(ve, ep):
    """`ve compile` the episode's scene.js (free, no LLM): {"errors": [...], "storyboard": {...}}."""
    (ep / "build3d").mkdir(parents=True, exist_ok=True)
    out = ep / "build3d" / "storyboard.json"
    try:
        r = subprocess.run(["node", str(ve / "ve.mjs"), "compile", str(ep / "scene.js"), str(out), "--json"],
                           capture_output=True, text=True, cwd=str(ve), timeout=120)
        res = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return {"errors": [f"could not compile scene.js: {e}"], "storyboard": {}}
    try:
        sb = json.loads(out.read_text())
    except (OSError, ValueError):
        sb = {}
    return {"errors": list(res.get("errors") or ([] if res.get("ok") else ["scene.js did not compile"])), "storyboard": sb}


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


SHORT_MIN_WORDS, SHORT_MAX_WORDS = 150, 260   # owner, 2026-11-15: a Short runs 50-90 s; ~3.1 words/s with the scene gaps (factory pipeline/rules.mjs)
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
        if factory_styles.is_iso(factory_styles.ticked(ctx.ws)):   # Isometric Pastel: Claude writes the animation (owner, 2026-11-14)
            return self._plan_iso(ctx, root, ep, slug, subject, topic, guidance)
        if factory_styles.is_3d(factory_styles.ticked(ctx.ws)):   # the 3D look: its own pipeline plans the video (owner, 2026-11-13)
            return self._plan_3d(ctx, root, ep, slug, subject, topic, guidance)
        prompt = "\n".join(x for x in [
            f"Make the next YouTube Short for this channel, as episode `episodes/{slug}/` of shorts-factory.",
            f"Topic: {subject}" if subject else f"Pick a fresh topic for the category below (not one of the recent videos).",
            f"Angle: {topic.get('angle')}" if topic.get("angle") and topic.get("angle") != subject else "",
            f"Category: {ctx.cat['label']}: {ctx.cat.get('brief', '')}",
            ("Owner's plan for this video:\n" + json.dumps(topic["owner_plan"], ensure_ascii=False, indent=1)) if topic.get("owner_plan") else "",
            ("Recent videos (do not repeat): " + "; ".join(_recent(ctx))) if _recent(ctx) else "",
            "",
            SKILL_RULE,
            factory_styles.instruction(factory_styles.ticked(ctx.ws)),
            "Follow CLAUDE.md and the explainer-short-style skill exactly, as for any video in this workspace. Use the existing episodes as",
            "examples of the files. Write ONLY these two files:",
            f"  shorts-factory/episodes/{slug}/script.json   (the scenes and narration)",
            f"  shorts-factory/episodes/{slug}/youtube.json  (title, description, tags, privacyStatus \"private\"; video \"../../out/{slug}-hyperframes.mp4\", captions \"../../out/{slug}.srt\")",
            "Any per-episode assets go in that episode folder. Do NOT render, do NOT run npm, do NOT upload, and do NOT change the skill,",
            "the templates or the pipeline. When the two files are written, answer with one line: DONE.",
            ("\nThe owner's notes on the last attempt (fix these):\n- " + "\n- ".join(guidance)) if guidance else "",
        ] if x is not None)
        out = self._claude(ctx, prompt, WRITER_TOOLS, root.parent)
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
                "story_problems": story_problems(script), "ticked": factory_styles.ticked(ctx.ws)}

    def _claude(self, ctx, prompt, tools, cwd, add_dirs=()):
        """One Claude Code session (the agent's model and budget from Settings): writes files with the given tools, answers DONE."""
        s = agent_settings(ctx.cfg, self.id)
        binary = ctx.cfg["llm"].get("claude_path") or "claude"
        cmd = [binary, "-p", "--output-format", "json", "--no-session-persistence", "--model", str(s.get("model", "sonnet")),
               "--max-budget-usd", str(max(float(s.get("max_budget_usd", 1.0)), 2.0)),
               "--permission-mode", "acceptEdits", "--allowedTools", ",".join(tools), "--tools", ",".join(tools)]
        for d in add_dirs:
            cmd += ["--add-dir", str(d)]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=str(cwd),
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
        return out

    def _plan_3d(self, ctx, root, ep, slug, subject, topic, guidance=None):
        """The 3D look (owner, 2026-11-14): one Claude Code session writes the storyboard program for video-engine (scene.js, following the
        engine's RULES.md) and the title, and checks it with `ve compile` (free, no LLM) until it is clean. The factory's make3d.mjs then
        voices it with the channel voice and renders it; nothing in the engine calls an LLM."""
        ve = engine_dir(ctx.cfg)
        if not (ve / "RULES.md").exists():
            raise AgentError(f"video-engine is not at {ve}: set video.engine_path in Settings or POSTCREW_VIDEO_ENGINE", fatal=True)
        fmt = (ctx.cat.get("format") or (ctx.video or {}).get("format") or "short") if hasattr(ctx, "cat") else "short"
        long = fmt == "long"
        seconds = int((ctx.video or {}).get("target_seconds") or (480 if long else 55))
        budget = int(seconds * WORDS_PER_SECOND_3D) if long else SHORT_MAX_WORDS_3D
        ep.mkdir(parents=True, exist_ok=True)
        (ep / "script.json").write_text(json.dumps({"style": "3d", "topic": subject or ctx.cat["label"], "format": "long" if long else "short",
                                                    "seconds": seconds}, ensure_ascii=False, indent=2) + "\n")
        fixing = bool(guidance) and (ep / "scene.js").exists() and (ep / "youtube.json").exists()   # a retry fixes, it does not rewrite
        if not fixing:
            for f in ("scene.js", "youtube.json"):
                (ep / f).unlink(missing_ok=True)
        compile_cmd = f"node {ve}/ve.mjs compile scene.js build3d/storyboard.json"
        prompt = "\n".join(x for x in [
            f"Make the next YouTube {'long video' if long else 'Short'} for this channel as an isometric 3D explainer. You are in its episode folder.",
            f"Topic: {subject}" if subject else "Pick a fresh topic for the category below (not one of the recent videos).",
            f"Angle: {topic.get('angle')}" if topic.get("angle") and topic.get("angle") != subject else "",
            f"Category: {ctx.cat['label']}: {ctx.cat.get('brief', '')}",
            ("Owner's plan for this video:\n" + json.dumps(topic["owner_plan"], ensure_ascii=False, indent=1)) if topic.get("owner_plan") else "",
            ("Recent videos (do not repeat): " + "; ".join(_recent(ctx))) if _recent(ctx) else "",
            "",
            f"Format: {'16:9 long video' if long else '9:16 Short (vertical)'}, target {seconds} s. Word budget (hard): at most {budget} spoken words"
            + (f" and at least {int(budget * .85)}" if long else "")
            + (f" and at least {int(budget * .85)}" if long else f" and at least {SHORT_MIN_WORDS_3D}") + ("" if long else ", one idea explained properly (what it is, why it matters, how it works, a worked example), 12-18 beats; the Short must run 50-90 s with the channel voice") + ". "
            "A like / comment / share / subscribe outro is added after your last beat automatically: do not write one.",
            "Write the narration and the visuals together as ONE storyboard program, following the rules below exactly (parts A and B;",
            f"part C is the format; read {ve}/examples/dijkstra.scene.js only if you need a full example).",
            "Write ONLY these two files in this folder:",
            "  scene.js      the program: function build(sb) { ... }",
            f"  youtube.json  {{\"title\", \"description\", \"tags\": [...], \"privacyStatus\": \"private\", \"video\": \"../../out/{slug}-hyperframes.mp4\", \"captions\": \"../../out/{slug}.srt\"}}",
            f"Then run `{compile_cmd}` and fix scene.js until it reports no errors (each run is free). Do NOT render and do NOT voice anything.",
            "When it compiles cleanly, answer with one line: DONE.",
            ("\nThe owner's notes on the last attempt (fix these):\n- " + "\n- ".join(guidance)) if guidance and not fixing else "",
            ("\nscene.js and youtube.json are already written. Do NOT rewrite them: edit scene.js only where needed to fix these problems, "
             "then compile again:\n- " + "\n- ".join(guidance)) if fixing else "",
            "",
            "=== RULES.md (video-engine) ===",
            (ve / "RULES.md").read_text(),
        ] if x is not None)
        self._claude(ctx, prompt, ["Read", "Write", "Edit", "Glob", "Grep", f"Bash(node {ve}/ve.mjs compile:*)"], ep, add_dirs=[ve])
        try:
            meta = json.loads((ep / "youtube.json").read_text())
        except (OSError, ValueError) as e:
            raise AgentError(f"youtube.json was not written correctly: {e}")
        check = compile_storyboard(ve, ep)
        beats = check["storyboard"].get("beats") or []
        said = " ".join(str(b.get("say") or "") for b in beats)
        return {"slug": slug, "episode": str(ep), "skill": skill_version(root), "title": meta.get("title", ""), "description": meta.get("description", ""),
                "tags": meta.get("tags") or [], "scene_count": len(beats), "narration": said[:4000], "words": len(said.split()), "long": long,
                "kind": "3d", "style": "3d", "code_scenes": 0, "story_problems": [], "ticked": ["3d"],
                "storyboard_errors": check["errors"], "word_budget": budget}

    def _plan_iso(self, ctx, root, ep, slug, subject, topic, guidance=None):
        """The Isometric Pastel look (owner, 2026-11-14): one Claude Code session writes the narration beats and the 2D-canvas animation
        (explainer.js) in the style of the owner's reference prompt (shorts-factory/styles/iso-pastel), then runs the storyboard check
        (free: key frames + automatic checks) and looks at the storyboard until it is clean. make-iso.mjs then voices and records it."""
        kit = root / "styles" / "iso-pastel"
        if not (kit / "STYLE.md").exists():
            raise AgentError(f"the Isometric Pastel kit is not at {kit}: update the Shorts factory", fatal=True)
        fmt = (ctx.cat.get("format") or (ctx.video or {}).get("format") or "short") if hasattr(ctx, "cat") else "short"
        long = fmt == "long"
        seconds = int((ctx.video or {}).get("target_seconds") or (480 if long else 50))
        budget = int(seconds * WORDS_PER_SECOND_3D) if long else SHORT_MAX_WORDS_ISO
        ep.mkdir(parents=True, exist_ok=True)
        fixing = bool(guidance) and all((ep / f).exists() for f in ("script.json", "explainer.js", "youtube.json"))
        if not fixing:
            for f in ("script.json", "explainer.js", "youtube.json"):
                (ep / f).unlink(missing_ok=True)
        check_cmd = "node ../../pipeline/make-iso.mjs . --check"
        prompt = "\n".join(x for x in [
            f"Make the next YouTube {'long video' if long else 'Short'} for this channel in the Isometric Pastel look. You are in its episode folder.",
            f"Topic: {subject}" if subject else "Pick a fresh topic for the category below (not one of the recent videos).",
            f"Angle: {topic.get('angle')}" if topic.get("angle") and topic.get("angle") != subject else "",
            f"Category: {ctx.cat['label']}: {ctx.cat.get('brief', '')}",
            ("Owner's plan for this video:\n" + json.dumps(topic["owner_plan"], ensure_ascii=False, indent=1)) if topic.get("owner_plan") else "",
            ("Recent videos (do not repeat): " + "; ".join(_recent(ctx))) if _recent(ctx) else "",
            "",
            f"Format: {'16:9 long video (1920x1080)' if long else '9:16 Short (1080x1920, vertical)'}. Word budget (hard): at most {budget} spoken words"
            + ("" if long else f" and at least {SHORT_MIN_WORDS_ISO}; aim for 165-205 words in 12-15 beats (about 65-75 s, the owner's house standard), one idea explained properly (what it is, why it matters, how it works, a worked example)") + ". "
            "The like / comment / share / subscribe outro is added after your last beat automatically: do not write one.",
            f"Read {kit}/STYLE.md (the rules, below), then the two house-standard Shorts in {kit}/examples/ (database-scaling, how-llms-work: match their "
            f"structure, look and timing exactly, change only the topic) and {kit}/reference.js (the style itself). "
            f"{kit}/kit.js has the drawing helpers you may call (box, cylinder, tag, numberTag, arrow, shade, poly).",
            "Write ONLY these files in this folder:",
            '  script.json   {"style": "iso", "topic": "...", "format": "' + ("long" if long else "short") + '", "beats": [{"say": "..."}, ...]}',
            "  explainer.js  function explainer(ctx, W, H_, t) { ... }  and  function scoreSound(k) { ... }",
            f"  youtube.json  {{\"title\", \"description\", \"tags\": [...], \"privacyStatus\": \"private\", \"video\": \"../../out/{slug}-hyperframes.mp4\", \"captions\": \"../../out/{slug}.srt\"}}",
            f"Then run `{check_cmd}` (free: no voice, no render). It writes build-iso/storyboard.png and lists problems. Fix every problem, "
            "then Read build-iso/storyboard.png and fix every panel that is empty, cramped, unreadable, off-screen or not clearly about its line. "
            "Repeat until both are clean. Do NOT render the video.",
            "When it is clean, answer with one line: DONE.",
            ("\nThe owner's notes on the last attempt (fix these):\n- " + "\n- ".join(guidance)) if guidance and not fixing else "",
            ("\nThe files are already written. Do NOT start over: edit them only where needed to fix these problems, then check again:\n- "
             + "\n- ".join(guidance)) if fixing else "",
            "",
            "=== STYLE.md (styles/iso-pastel) ===",
            (kit / "STYLE.md").read_text(),
        ] if x is not None)
        self._claude(ctx, prompt, ["Read", "Write", "Edit", "Glob", "Grep", f"Bash({check_cmd}:*)"], ep, add_dirs=[kit])
        try:
            meta = json.loads((ep / "youtube.json").read_text())
            script = json.loads((ep / "script.json").read_text())
        except (OSError, ValueError) as e:
            raise AgentError(f"youtube.json or script.json was not written correctly: {e}")
        problems = iso_check(root, ep)
        beats = [b for b in (script.get("beats") or []) if str(b.get("say") or "").strip()]
        said = " ".join(str(b.get("say")) for b in beats)
        return {"slug": slug, "episode": str(ep), "skill": skill_version(root), "title": meta.get("title", ""), "description": meta.get("description", ""),
                "tags": meta.get("tags") or [], "scene_count": len(beats), "narration": said[:4000], "words": len(said.split()), "long": long,
                "kind": "iso", "style": "iso", "code_scenes": 0, "story_problems": [], "ticked": ["iso"],
                "storyboard_errors": problems, "word_budget": budget, "storyboard": str(ep / "build-iso" / "storyboard.png")}

    def validate(self, ctx, out):
        p = []
        if not out.get("title"):
            p.append("youtube.json has no title")
        if not out.get("scene_count"):
            p.append("script.json has no scenes")
        if out.get("style") == "iso":
            p += [f"storyboard check: {e}" for e in (out.get("storyboard_errors") or [])[:8]]
            if out.get("words", 0) > out.get("word_budget", SHORT_MAX_WORDS_ISO):
                p.append(f"the narration has {out['words']} words, over the budget of {out['word_budget']}: merge or cut beats in script.json")
            if not out.get("long") and out.get("words", 0) < SHORT_MIN_WORDS_ISO:
                p.append(f"the narration has only {out['words']} words: a Short runs at least 50 s ({SHORT_MIN_WORDS_ISO}+ words). Explain more: "
                         f"why it matters, how it works step by step, a worked example (owner, 2026-11-15)")
            return p
        if out.get("style") == "3d":
            p += [f"scene.js: {e}" for e in (out.get("storyboard_errors") or [])[:8]]
            if not out.get("long") and out.get("words", 0) < SHORT_MIN_WORDS_3D:
                p.append(f"the narration has only {out['words']} words: a Short runs at least 50 s ({SHORT_MIN_WORDS_3D}+ words). Explain more: "
                         f"why it matters, how it works step by step, a worked example (owner, 2026-11-15)")
            if out.get("words", 0) > out.get("word_budget", SHORT_MAX_WORDS_3D):
                p.append(f"the narration has {out['words']} words, over the budget of {out['word_budget']}: merge or cut beats in scene.js")
            return p
        if not out.get("long") and out.get("words", 0) > SHORT_MAX_WORDS:   # the owner's 90-second limit (2026-11-15), before any render
            p.append(f"the narration has {out['words']} words: a Short is at most 90 seconds, {SHORT_MAX_WORDS} words. Cut whole scenes "
                     f"(one idea per Short) and write script.json again")
        if not out.get("long") and 0 < out.get("words", 0) < SHORT_MIN_WORDS:   # ... and at least 50 seconds (owner, 2026-11-15)
            p.append(f"the narration has only {out['words']} words: a Short runs at least 50 seconds, {SHORT_MIN_WORDS}+ words. Explain a "
                     f"bit more (why it matters, how it works step by step, a worked example) and write script.json again")
        if not out.get("long") and out.get("kind") != "algorithm" and out.get("style") != "story" and "story" in out.get("ticked", ["story"]):
            p.append("the Story look is ticked, so an explainer Short is a Story video: set \"style\": \"story\" and tell it with the cast in a "
                     "fitting background, as references/story-style.md says. Only algorithm problems (\"kind\": \"algorithm\") keep the Signal look")
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
