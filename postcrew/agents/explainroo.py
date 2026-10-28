"""Explainroo Producer (YouTube): makes the video with explainroo (https://www.explainroo.com), an open-source tool that
turns `script.md` (what the voice says) and `scenes.js` (what is drawn, each thing on a spoken word) into an MP4 with a camera
that follows the narration, hand-drawn lines, icons, charts, code, sound effects and music. It runs on this computer.

The voice is made first by the Voice step (ElevenLabs): each scene's recording is given to explainroo as the narration, so the
words, the pauses and the voice are the ones that were approved. An AI agent (Claude Code, the same login as the rest of the crew)
then writes `scenes.js`: the pictures, tied to the spoken words. Postcrew runs explainroo's own checks and feeds every problem
back until it is clean, looks at the contact sheet once, renders, and verifies the file.

Setup: Settings > YouTube > Video renderer > Explainroo; the folder where explainroo is installed is `video.explainroo.path`.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from ..render import video as video_mod
from .base import AgentError
from .video import VideoAgent

SIZES = {"short": "shorts", "long": "youtube"}
NOTES = {
    "type": "object",
    "properties": {"notes": {"type": "string", "description": "one or two sentences: what you drew and anything you could not do"}},
    "required": ["notes"],
    "additionalProperties": False,
}
MAX_FIX_ROUNDS = 6
TOOLS = ("Read", "Write", "Edit", "Glob", "Grep")


def _words(text):
    return re.findall(r"[a-z0-9']+", re.sub(r"\[[^\]]*\]|\{([^|{}]*)\|[^}]*\}", lambda m: m.group(1) or "", str(text).lower()))


def narration_of(script_md):
    """The words of a script.md the voice speaks (markers, settings, notes and headings left out)."""
    out = []
    for line in script_md.splitlines():
        if line.startswith(("#", ">")) or not line.strip():
            continue
        out += _words(line)
    return out


class ExplainrooAgent(VideoAgent):
    title = "Explainroo Producer"
    name = "Roo"
    role = ("Makes the video with explainroo: the approved voice, hand-drawn pictures that appear on the words that are spoken, "
            "a camera that follows the narration, sound effects and music.")
    renderer = "explainroo"
    uses_llm = True

    # ---------- setup ----------
    @staticmethod
    def settings(ctx):
        cfg = dict(ctx.cfg["video"].get("explainroo") or {})
        cfg.setdefault("path", "")
        cfg.setdefault("theme", "midnight")
        cfg.setdefault("music", "calm")
        cfg.setdefault("watermark", False)
        cfg.setdefault("review", True)
        return cfg

    def tool(self, ctx):
        cfg = self.settings(ctx)
        root = Path(str(cfg["path"]).strip()).expanduser()
        if not cfg["path"] or not (root / "bin" / "explainroo.js").exists():
            raise AgentError("explainroo is not installed: set Settings > YouTube > Explainroo folder (git clone "
                             "https://github.com/vincentsch/explainroo.git, then npm install and node bin/explainroo.js doctor --fetch)",
                             fatal=True)
        if not (root / "node_modules").exists():
            raise AgentError(f"explainroo in {root} has no node_modules: run npm install there", fatal=True)
        if not shutil.which("node"):
            raise AgentError("Node.js 20.11 or newer is needed for explainroo (brew install node)", fatal=True)
        return root, cfg

    def node(self, root, *args, timeout=1800):
        r = subprocess.run(["node", "bin/explainroo.js", *args], cwd=root, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    # ---------- the project ----------
    def project(self, ctx, root, cfg, script, audio):
        rid = ctx.run.status["run_id"]
        rel = f"videos/postcrew-{rid}"
        proj = root / rel
        if proj.exists():
            shutil.rmtree(proj)
        rc, out = self.node(root, "init", rel, "--theme", str(cfg["theme"]), "--size", SIZES.get(ctx.video["format"], "shorts"),
                            "--title", script["title"][:80])
        if rc:
            raise AgentError(f"explainroo init failed: {out.strip()[-300:]}")
        vj = json.loads((proj / "video.json").read_text())
        vj.update(music=cfg["music"], watermark=cfg["watermark"] or False, captions=bool(ctx.cfg["video"].get("captions", True)))
        scenes = script["scenes"]
        ids = [f"scene{i}" for i in range(1, len(scenes) + 1)]
        md = [f"# {script['title']}", ""]
        for i, sc in zip(ids, scenes):
            md += [f"## {i} {{hold=0.9}}", " ".join(str(sc["narration"]).split()), ""]
        if audio and len(audio) == len(scenes):   # the approved ElevenLabs recordings, one per scene
            folder = proj / "assets" / "narration"
            folder.mkdir(parents=True, exist_ok=True)
            for i, f in zip(ids, audio):
                shutil.copy(f, folder / f"{i}{Path(f).suffix or '.mp3'}")
            vj["voice"] = {"provider": "recording", "src": "assets/narration/"}
        else:
            vj["voice"] = ctx.cfg["video"].get("explainroo", {}).get("kokoro_voice", "af_heart")
        (proj / "video.json").write_text(json.dumps(vj, indent=2))
        (proj / "script.md").write_text("\n".join(md))
        return rel, proj, ids

    def brief(self, ctx, script, ids, rel):
        lines = []
        for i, sc in zip(ids, script["scenes"]):
            vis = {k: sc[k] for k in ("layout", "on_screen", "items", "nodes", "edges", "cells", "steps", "code", "language")
                   if sc.get(k)}
            lines.append(f"### {i}\nnarration: {sc['narration']}\nthe script writer's picture plan: {json.dumps(vis, ensure_ascii=False)}")
        return (f"Make the pictures for the video in {rel}/ (script.md is already written and the voice is recorded).\n"
                f"Topic: {ctx.outputs['topic']['topic']}\nFormat: {ctx.video['format']} ({SIZES.get(ctx.video['format'])})\n\n"
                "Read AGENTS.md first (the sections 'What makes the pictures good' and 'Scene API' at least), then write "
                f"{rel}/scenes.js with one function per scene id below, tying each picture to a spoken word with at:'word' or a "
                f"[#marker] you add to script.md.\n\nTHE SCENES:\n\n" + "\n\n".join(lines))

    def fix_brief(self, rel, report):
        return (f"explainroo's check of {rel} found these problems. Fix every error and every warning in {rel}/scenes.js "
                f"(and markers in {rel}/script.md), then stop:\n\n{report}")

    # ---------- the loop ----------
    def ask_roo(self, ctx, root, system, prompt):
        from ..llm import LLMError
        try:
            res = ctx.llm.call("explainroo", system, prompt, NOTES, tools=TOOLS, cwd=str(root))
        except LLMError as e:
            ctx.run.add_cost(self.id, e.cost_usd)
            raise AgentError(f"LLM {e.kind}: {e}", fatal=e.kind in ("not_installed", "auth", "limit"))
        ctx.run.add_cost(self.id, res.cost_usd)
        ctx.run.add_tokens(self.id, res.tokens)
        ctx.run.event(self.id, "llm", f"{res.model or 'model'} answered in {res.duration_s}s ($ {res.cost_usd:.3f}): "
                                      f"{str((res.data or {}).get('notes', ''))[:160]}")
        return res.data or {}

    def problems(self, root, rel):
        rc, out = self.node(root, "check", rel, "--json")
        try:
            data = json.loads(out[out.index("{"):])
        except ValueError:
            return [out.strip()[-600:]] if rc else []
        found = []
        for p in data.get("issues") or []:
            if "voice check" in str(p.get("message", "")):
                continue   # the recording is the approved ElevenLabs voice: a word it says differently is not the picture's problem
            where = f"{p.get('scene', '')}" + (f" at {p['t']}s" if p.get("t") is not None else "")
            found.append(f"{p.get('level', 'error')}: {where}: {p.get('message', '')}")
        return found

    def render(self, ctx, scenes, audio, out_path, work, kicker, handle):
        root, cfg = self.tool(ctx)
        script = ctx.outputs["writer"]
        rel, proj, ids = self.project(ctx, root, cfg, script, audio)
        spoken = narration_of((proj / "script.md").read_text())
        system = self.prompt(ctx, "explainroo")
        ctx.run.event(self.id, "project", f"explainroo project {rel}: {len(ids)} scenes, theme {cfg['theme']}, "
                                          f"{'the approved ElevenLabs recordings' if audio else 'the local Kokoro voice'} as narration")
        self.ask_roo(ctx, root, system, self.brief(ctx, script, ids, rel))
        bad = []
        for round_ in range(MAX_FIX_ROUNDS + 1):
            if not (proj / "scenes.js").exists():
                raise AgentError("the agent did not write scenes.js")
            if narration_of((proj / "script.md").read_text()) != spoken:
                raise AgentError("the agent changed the words in script.md: the voice was recorded from the approved script")
            bad = self.problems(root, rel)
            ctx.run.event(self.id, "check", f"explainroo check: {len(bad)} problem(s)" + (f" (round {round_ + 1})" if round_ else ""))
            if not bad or round_ == MAX_FIX_ROUNDS:
                break
            self.ask_roo(ctx, root, system, self.fix_brief(rel, "\n".join(f"- {b}" for b in bad)[:6000]))
        errors = [b for b in bad if b.startswith("error")]
        if errors:
            raise AgentError("explainroo still reports errors in the pictures: " + "; ".join(errors)[:600])
        if cfg.get("review", True):   # the agent cannot watch a video: it looks at the end of every scene and the contact sheet
            for turn in range(2):
                rc, _ = self.node(root, "still", rel)
                rc2, _ = self.node(root, "sheet", rel)
                stills = sorted(p.relative_to(root).as_posix() for p in (proj / "out" / "stills").glob("*.png")) \
                    if (proj / "out" / "stills").exists() else []
                if rc or not stills:
                    break
                self.ask_roo(ctx, root, system,
                             f"Review round {turn + 1}. Read these pictures (the end of every scene) and the contact sheet "
                             f"{rel}/out/sheet.jpg:\n" + "\n".join(stills) + "\n\nJudge like a viewer: does each scene show the example moving "
                             "(array, pointers, arithmetic, request and data) and not just labels? Is any text cut off, tiny, or on "
                             "top of an icon or another shape (icons beside text, never under it)? Is the area inside the safe "
                             "zone used well, not a few small things? Is every scene different from the last? Fix what is wrong "
                             f"in {rel}/scenes.js; if it is all good, change nothing.")
                again = self.problems(root, rel)
                ctx.run.event(self.id, "review", f"after review round {turn + 1}: {len(again)} problem(s)")
                for fix in range(3):
                    if not again:
                        break
                    self.ask_roo(ctx, root, system, self.fix_brief(rel, "\n".join(f"- {b}" for b in again)[:6000]))
                    again = self.problems(root, rel)
                if any(b.startswith("error") for b in again):
                    raise AgentError("explainroo still reports errors in the pictures after the review: " + "; ".join(again)[:600])
        ctx.run.event(self.id, "render", "rendering with explainroo (this takes a few minutes)")
        rc, out = self.node(root, "render", rel, timeout=3600)
        made = proj / "out" / "video.mp4"
        if rc or not made.exists():
            raise AgentError(f"explainroo render failed: {out.strip()[-400:]}")
        rc, vout = self.node(root, "verify", rel)
        ctx.run.event(self.id, "verify", "explainroo verify: " + (vout.strip().splitlines()[-1] if vout.strip() else "ok"),
                      level="info" if rc == 0 else "warning")
        out_path = Path(out_path)
        shutil.copy(made, out_path)
        for ext in (".srt", ".vtt", ".chapters.txt"):
            extra = proj / "out" / f"video{ext}"
            if extra.exists():
                shutil.copy(extra, out_path.with_suffix(ext))
        try:
            info = video_mod.probe(out_path)
        except video_mod.VideoError as e:
            raise AgentError(f"the explainroo video is not readable: {e}")
        return {"seconds": info["seconds"], "width": info["width"], "height": info["height"], "timeline": None}, self.renderer
