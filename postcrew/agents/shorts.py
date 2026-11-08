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
WRITER_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"]


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
        return {"slug": slug, "episode": str(ep), "title": meta.get("title", ""), "description": meta.get("description", ""),
                "tags": meta.get("tags") or [], "scene_count": len(script.get("scenes") or []),
                "narration": " ".join(str(sc.get("say") or sc.get("narration") or sc.get("voice") or "") for sc in script.get("scenes") or [])[:4000]}

    def validate(self, ctx, out):
        p = []
        if not out.get("title"):
            p.append("youtube.json has no title")
        if not out.get("scene_count"):
            p.append("script.json has no scenes")
        return p

    def summary(self, out):
        return f"{out['title']} ({out['scene_count']} scenes)"


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
