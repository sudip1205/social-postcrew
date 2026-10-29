"""Hooks (YouTube): the quality gate every video passes before it is queued. No AI.

It looks at the finished file the way a viewer would, in seconds and for free: is there sound where the voice should speak (and no
long silence, wrong loudness or clipping), are the frames right (no black frames, nothing frozen for ages, no empty scene, nothing
drawn at the edge), is the size right, and for an explainroo video does the voice stop where the punctuation says and does every word
match. An earlier video needed four or five tries because such faults were only found by watching it; now they are found at once and
only the scene that is wrong is fixed (a voice recorded again, one scene's picture redrawn, then a new render), once.

Its id is "hooks"; it runs after the Video Producer and the Video Editor, before the Publisher.
"""
import json
from pathlib import Path

from ..render import qa
from ..render import video as video_mod
from .base import Agent, AgentError
from .explainroo import ExplainrooAgent, pause_problems


class HooksAgent(Agent):
    id = "hooks"
    title = "Quality Hooks"
    name = "Hook"
    role = ("Checks the finished video without AI: sound where the voice should speak, a clean voice, and right frames. Fixes only the "
            "scene that is wrong, once, so a video does not need many tries.")
    uses_llm = False

    def applies(self, ctx):
        media = ctx.outputs.get("media") or {}
        return bool(media.get("path")) and not ctx.dry_run

    # ---------- what to look at ----------
    @staticmethod
    def layout(media, script):
        """([(start, end)] of the narration in each scene, [(start, end)] of each scene on screen, voiced?)."""
        ex = media.get("explainroo")
        if ex:
            try:
                t = json.loads((Path(ex["root"]) / ex["rel"] / "build" / "timeline.json").read_text())
                scenes = [(s["start"], s["start"] + s["dur"]) for s in t["scenes"]]
                spans = [(v["start"], v["end"]) for v in t["voiceSpans"]]
                return spans, scenes, True
            except (OSError, ValueError, KeyError):
                pass
        tl = media.get("timeline") or []
        scenes = [(e["start"], e["start"] + e["seconds"]) for e in tl]
        return [(a + 0.3, b - 0.3) for a, b in scenes], scenes, media.get("voice") not in (None, "none", "rehearsal")

    @staticmethod
    def voice_findings(media):
        """The voice against the punctuation, from explainroo's word times: stops in the wrong place after the retakes."""
        ex = media.get("explainroo")
        out = []
        if not ex:
            return out
        folder = Path(ex["root"]) / ex["rel"] / "build" / "voice"
        for f in sorted(folder.glob("scene*.json")):
            try:
                d = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            n = int("".join(c for c in f.stem if c.isdigit()) or 0)
            if (d.get("matchRate") or 1) < 0.9:
                out.append({"scene": n, "kind": "voice_words", "severity": "warn",
                            "message": f"scene {n}: the voice does not say the words as written ({round((d.get('matchRate') or 0) * 100)}% match): "
                                       f"{d.get('unconfirmed') or d.get('transcript', '')[:80]}"})
            for word, what in pause_problems(d.get("words") or [])[:3]:
                out.append({"scene": n, "kind": "voice_stop", "severity": "warn", "message": f"scene {n}: after '{word}' {what}"})
        return out

    def inspect(self, ctx, media):
        script = ctx.outputs["writer"]
        spans, scenes, voiced = self.layout(media, script)
        findings, score, facts = qa.inspect(media["path"], spans, scenes, voiced=voiced, fmt=ctx.video["format"], expect_seconds=media.get("seconds"))
        if media.get("renderer") != "explainroo":   # only an explainroo video is normalised and can be repaired: elsewhere these are notes
            for f in findings:
                if f["kind"] in ("loudness", "clipping"):
                    f["severity"] = "warn"
        findings += self.voice_findings(media)
        score = max(0, score - 3 * sum(1 for f in findings if f["kind"].startswith("voice_")))
        return findings, score, facts

    # ---------- the gate ----------
    def run(self, ctx, guidance):
        """Inspect; fix what can be fixed once (only for an explainroo video, whose scenes and voice can be redone cheaply); never fail the
        run for what cannot be fixed (retrying would only repeat the same check and the same cost): report it, and the Publisher holds
        the video for a person to approve."""
        media = ctx.outputs["media"]
        findings, score, facts = self.inspect(ctx, media)
        errors = [f for f in findings if f["severity"] == "error"]
        repaired = False
        ctx.run.event(self.id, "inspect", f"quality {score}/100: {len(errors)} error(s), {len(findings) - len(errors)} warning(s)"
                      + (f" (loudness {facts['audio']['lufs']} LUFS)" if facts.get("audio", {}).get("lufs") is not None else ""))
        can_fix = media.get("renderer") == "explainroo" and media.get("explainroo")
        if errors and can_fix and not ctx.flags.get("hooks_repaired"):
            ctx.flags["hooks_repaired"] = True   # once per run: a retry of this step must not pay for the same repair again
            for f in errors[:6]:
                ctx.run.event(self.id, "found", f["message"], level="warning")
            try:
                info = ExplainrooAgent().repair(ctx, media, errors)
            except AgentError as e:
                ctx.run.event(self.id, "repair_failed", str(e)[:200], level="warning")
            else:
                media.update(seconds=round(info["seconds"], 1), width=info["width"], height=info["height"])
                repaired = True
                findings, score, facts = self.inspect(ctx, media)
                errors = [f for f in findings if f["severity"] == "error"]
                ctx.run.event(self.id, "recheck", f"after the repair: quality {score}/100, {len(errors)} error(s)")
        for f in errors:
            if f["severity"] == "error":
                ctx.run.event(self.id, "unresolved", f["message"], level="warning")
        return {"score": score, "findings": findings, "repaired": repaired, "unresolved": [f["message"] for f in errors],
                "checked": sorted({f["kind"] for f in findings}) or ["clean"]}

    def validate(self, ctx, out):
        return []

    def summary(self, out):
        n = len(out.get("findings") or [])
        return (f"quality {out['score']}/100" + (f", {n} note(s)" if n else ", all clear") + (", repaired once" if out.get("repaired") else "")
                + (f", {len(out['unresolved'])} fault(s) left: held for your approval" if out.get("unresolved") else ""))
