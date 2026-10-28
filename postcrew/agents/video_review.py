"""Video Editor (YouTube): the second Editor, after the blackboard or explainer video is drawn. It checks that the graphics go with the voice.

The first Editor reviews the script; nothing looked at the finished video. This step does: it measures when each box, arrow and
bullet was drawn against when the voice says it (render/audit.py, on the real voice files), fixes a different order for free,
and asks an AI reviewer about the rest. Only the graphics change: the voice is never made again (the clips the Voice step
recorded are reused) and the narration is not in the reviewer's hands. Only the scenes that changed are drawn again.
"""
from .. import platforms
from ..checks import script_problems
from ..render import audit, timeline
from ..render import blackboard as bb
from ..render import explainer as ex
from ..render import video as video_mod
from .base import Agent, AgentError
from .script import STEP, finish

LAYOUTS = ["title", "statement", "points", "code", "diagram", "trace", "flow"]
VISUAL_KEYS = ("layout", "on_screen", "items", "nodes", "edges", "code", "language", "cells", "steps")
FIX = {
    "type": "object",
    "properties": {
        "scene": {"type": "integer", "description": "scene number, from 1"},
        "problem": {"type": "string"},
        "layout": {"type": "string", "enum": LAYOUTS},
        "on_screen": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "nodes": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "edges": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "code": {"type": "string"}, "language": {"type": "string"},
        "cells": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "steps": {"type": "array", "items": STEP, "maxItems": 12},
    },
    "required": ["scene", "problem", *VISUAL_KEYS],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["pass", "fix"]}, "score": {"type": "integer"},
                   "summary": {"type": "string"}, "scenes": {"type": "array", "items": FIX, "maxItems": 12}},
    "required": ["verdict", "score", "summary", "scenes"],
    "additionalProperties": False,
}
MAX_LLM_ROUNDS = 2


class VideoReviewAgent(Agent):
    id = "video_review"
    title = "Video Editor"
    name = "Cut"
    role = ("Watches the finished blackboard video against the voice: is each thing drawn when it is said? Fixes the graphics "
            "(never the voice) and draws the changed scenes again.")

    def applies(self, ctx):
        media = ctx.outputs.get("media") or {}
        return media.get("renderer") in ("blackboard", "explainer") and bool(media.get("timeline")) and media.get("voice") != "own"

    # ---------- the report the reviewer reads ----------
    @staticmethod
    def _report(scenes, entries, audios, findings):
        lines = []
        for i, (sc, t) in enumerate(zip(scenes, entries), 1):
            words, measured = timeline.voice_words(str(sc.get("narration", "")), t["seconds"], audios[i - 1] if audios else None)
            vis = {k: sc.get(k) for k in VISUAL_KEYS if sc.get(k)}
            lines.append(f"SCENE {i} ({t['seconds']:.1f}s, voice timing {'measured' if measured else 'estimated'})\n"
                         f"  narration: {sc.get('narration', '')}\n  drawn now: {vis}")
            for th in t["things"]:
                said = timeline.cue_time(th["cue"], words) if th["cue"] else None
                lines.append(f"    {th['start']:5.1f}s {th.get('what') or 'item':<12} {th['cue'] or '(heading)'}"
                             + (f"   voice says it at {said:.1f}s" if said is not None else "   voice never says it" if th["cue"] else ""))
        found = "\n".join(f"- {f['message']}" for f in findings) or "- none: the automatic check found everything in step"
        return "\n".join(lines) + f"\n\nAUTOMATIC FINDINGS:\n{found}"

    # ---------- drawing again ----------
    def _redraw(self, ctx, scenes, redo, audio, media):
        kicker = (ctx.cat.get("kicker") or ctx.cat["label"]).upper()[:26]
        try:
            info = (ex if media.get("renderer") == "explainer" else bb).render(scenes, media["path"], ctx.video["format"], ctx.run.dir / "frames", audio=audio,
                             handle=ctx.profile.get("handle", ""), kicker=kicker,
                             captions=bool(ctx.cfg["video"].get("captions", True)), redo=set(redo))
        except video_mod.VideoError as e:
            raise AgentError(f"drawing the changed scenes failed: {e}")
        media["timeline"], media["seconds"] = info["timeline"], round(info["seconds"], 1)
        return info["timeline"]

    def _apply(self, ctx, script, scenes, fixes):
        """The reviewer's replacements for the scenes' graphics, checked: a replacement that breaks a rule is left out."""
        changed, spec = [], ctx.video
        for f in fixes:
            n = f["scene"]
            if not 1 <= n <= len(scenes):
                continue
            new = dict(scenes[n - 1], **{k: f.get(k, scenes[n - 1].get(k)) for k in VISUAL_KEYS})   # the narration is never in the replacement
            new["items"] = [x for x in new["items"] if x][:5]
            if all(new[k] == scenes[n - 1].get(k) for k in VISUAL_KEYS):
                continue
            trial = scenes[:n - 1] + [new] + scenes[n:]
            before = {p for p in script_problems(finish(dict(script, scenes=scenes)), spec, ctx.cat, ctx.profile) if p.startswith(f"scene {n}:")}
            after = {p for p in script_problems(finish(dict(script, scenes=trial)), spec, ctx.cat, ctx.profile) if p.startswith(f"scene {n}:")}
            if after - before:
                ctx.run.event(self.id, "rejected_fix", f"scene {n}: the suggested graphics break a rule ({sorted(after - before)[0]}); "
                                                       f"kept as they were", level="warning")
                continue
            scenes[n - 1] = new
            changed.append(n - 1)
        return changed

    def run(self, ctx, guidance):
        script, media = ctx.outputs["writer"], ctx.outputs["media"]
        voice = ctx.outputs.get("voice") or {}
        audio = voice.get("files") or None   # the voice recorded before: reused as it is, never made again
        scenes = [dict(sc) for sc in script["scenes"]]
        if len(media["timeline"]) != len(scenes):
            raise AgentError("the video and the script do not have the same scenes", fatal=True)
        findings, first, measured = audit.check(scenes, media["timeline"], audio)
        ctx.run.event(self.id, "sync", f"sync score {first}/100 ({'measured on the voice' if measured else 'estimated: no voice recorded'}); "
                                       f"{len(findings)} finding(s)")
        redrawn, fixed = set(), []
        scenes_fixed, changed = audit.autofix(scenes, media["timeline"], audio)   # free: list things in the order they are said
        if changed:
            scenes = scenes_fixed
            fixed += [f"scene {i + 1}: arrows/points put in the order the voice explains them" for i in changed]
            self._redraw(ctx, scenes, changed, audio, media)
            redrawn |= set(changed)
            findings, score, measured = audit.check(scenes, media["timeline"], audio)
            ctx.run.event(self.id, "reordered", f"reordered {len(changed)} scene(s) to follow the voice; sync score now {score}/100")
        review, rounds = {}, 0
        while rounds < MAX_LLM_ROUNDS:
            rounds += 1
            system = self.prompt(ctx)
            review = self.ask(ctx, system, self._report(scenes, media["timeline"], audio, findings), SCHEMA)
            fixes = review.get("scenes") if review.get("verdict") == "fix" else []
            changed = self._apply(ctx, script, scenes, fixes or [])
            if not changed:
                break
            fixed += [f"scene {f['scene']}: {f['problem']}" for f in fixes if f["scene"] - 1 in changed]
            self._redraw(ctx, scenes, changed, audio, media)
            redrawn |= set(changed)
            findings, score, measured = audit.check(scenes, media["timeline"], audio)
            ctx.run.event(self.id, "redrawn", f"drew scene(s) {', '.join(str(i + 1) for i in sorted(changed))} again with the same voice; "
                                              f"sync score now {score}/100")
            if not any(f["severity"] == "error" for f in findings):
                break
        findings, score, measured = audit.check(scenes, media["timeline"], audio)
        if redrawn:   # the visuals the video really shows (the narration, and so the voice, is exactly as it was)
            ctx.outputs["writer"] = finish(dict(script, scenes=scenes))
        errors = [f for f in findings if f["severity"] == "error"]
        for f in errors:
            ctx.run.event(self.id, "warning", f["message"], level="warning")
        return {"verdict": "passed" if not errors else "needs_attention", "score": score, "first_score": first,
                "measured": measured, "llm_score": review.get("score"), "summary": review.get("summary", ""),
                "rounds": rounds, "redrawn": sorted(i + 1 for i in redrawn), "fixed": fixed, "remaining": findings,
                "voice_regenerated": False}

    def validate(self, ctx, out):
        return []   # the video exists and was checked; what is still off is reported to the owner, not retried

    def summary(self, out):
        left = len([f for f in out["remaining"] if f["severity"] == "error"])
        base = f"sync {out['score']}/100" + (f" (was {out['first_score']})" if out["first_score"] != out["score"] else "")
        return (base + (f", redrew scene(s) {', '.join(map(str, out['redrawn']))} with the same voice" if out["redrawn"] else ", nothing to change")
                + (f"; {left} mismatch(es) left" if left else ""))
