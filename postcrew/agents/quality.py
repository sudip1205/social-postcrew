"""Quality Director (YouTube): looks at the finished video the way a viewer would, and sends weak scenes back to be drawn again.

The Editor judges the script and Quality Hooks checks the sound and the file; nobody looked at the PICTURE. This agent does, in two parts:

1. Measured, no AI (motion/frames.py): frames of every scene at 40% and 92% of its length. An empty screen, a picture that fills only a
   sliver of the screen at the end of its scene, and a picture that does not change for many seconds are found for free.
2. A vision model sees contact sheets of those frames with each scene's narration, the Creative Director's plan, the house style and your
   approved preferences, and scores readability on a phone, use of the screen, clarity, motion, variety and style (0-100). For every weak
   scene it gives the complete replacement picture (layout, words on screen, boxes, arrows, code...), never the narration.

When the video scores under video.motion.min_score (default 75) or a scene is empty, the replacements are checked against the script's rules
(the same check the Storyboard Artist's changes pass) and the video is drawn again from the frame steps: the voice is reused, so a redraw
costs only rendering time. At most video.motion.max_redraws times (default 1). A video still under video.motion.hold_below (default 60), or
with an empty scene left, waits for your approval whatever the approval setting.
"""
import shutil
from pathlib import Path

from ..motion import frames as fr
from ..motion import library as lib
from .base import Agent, AgentError
from .direction import motion_cfg
from .graphics import FIX as GRAPHICS_FIX
from .graphics import GraphicsAgent
from .script import finish

EMPTY_FILL = 0.006       # less than this share of the picture area is content: an empty screen
SPARSE_HEIGHT = 0.2      # content spans less than this share of the picture area's height...
SPARSE_FILL = 0.04       # ...and covers less than this: a sliver of a picture
STILL_CHANGE = 4.5       # pictures this similar (frames.change) count as not changing
SAMPLES = (0.4, 0.92)
CRITERIA = ["readability", "screen_use", "clarity", "motion", "variety", "style"]

FIX = {"type": "object",
       "properties": {"severity": {"type": "string", "enum": ["error", "warn"]},
                      "problem": {"type": "string", "description": "what a viewer sees that is wrong, in one sentence"},
                      "redraw": {"type": "boolean", "description": "true when the replacement picture fields below are given"},
                      **GRAPHICS_FIX["properties"]},
       "required": ["scene", "severity", "problem", "redraw"], "additionalProperties": False}
SCHEMA = {"type": "object", "properties": {
    "scores": {"type": "object", "properties": {c: {"type": "integer", "minimum": 0, "maximum": 100} for c in CRITERIA},
               "required": CRITERIA, "additionalProperties": False},
    "overall": {"type": "integer", "minimum": 0, "maximum": 100},
    "summary": {"type": "string"},
    "scenes": {"type": "array", "items": FIX, "maxItems": 30},
    "rewrite": {"type": "boolean", "description": "true only when redrawing scenes cannot fix it because the SCRIPT is wrong for its problem: the "
                                                  "data drawn as the wrong shape (a grid as one row, a tree as a list), the example is not the "
                                                  "problem's own, or the words describe things the pictures cannot show (above, below, left of)"},
    "rewrite_why": {"type": "string", "description": "when rewrite: what the script must change, in one or two sentences"}},
    "required": ["scores", "overall", "summary", "scenes"], "additionalProperties": False}


def spans(media, scenes):
    """[(start, end)] of every scene in the finished video, from what the renderer reports, else the script's estimate."""
    tl = media.get("timeline") or []
    if tl and len(tl) == len(scenes):
        return [(float(e["start"]), float(e["start"]) + float(e["seconds"])) for e in tl]
    secs = media.get("scene_seconds") or []
    if len(secs) != len(scenes):
        total = float(media.get("seconds") or 0)
        est = [max(float(s.get("seconds") or 0), 0.5) for s in scenes]
        secs = [total * e / sum(est) for e in est] if total and sum(est) else est
    out, t = [], 0.0
    for s in secs:
        out.append((t, t + float(s)))
        t += float(s)
    return out


def picture_findings(measures, still_s):
    """What a program sees in the frames of each scene: [{"scene", "kind", "severity", "message"}]."""
    out = []
    for m in measures:
        n, a, b = m["scene"], m["frames"][0], m["frames"][-1]
        secs = m["end"] - m["start"]
        if max(a["fill"], b["fill"]) < EMPTY_FILL:
            out.append({"scene": n, "kind": "empty", "severity": "error",
                        "message": f"scene {n}: the screen is empty ({secs:.0f}s with nothing but the captions)"})
            continue
        if b["height"] < SPARSE_HEIGHT and b["fill"] < SPARSE_FILL and a["height"] < SPARSE_HEIGHT:
            out.append({"scene": n, "kind": "sparse", "severity": "warn",
                        "message": f"scene {n}: the picture fills only {round(b['height'] * 100)}% of the screen's height"})
        if m.get("change") is not None and m["change"] < STILL_CHANGE and secs * (SAMPLES[1] - SAMPLES[0]) >= still_s:
            out.append({"scene": n, "kind": "still", "severity": "warn",
                        "message": f"scene {n}: the picture does not change for about {secs * (SAMPLES[1] - SAMPLES[0]):.0f}s"})
    return out


class QualityDirectorAgent(Agent):
    id = "quality"
    title = "Quality Director"
    name = "Lens"
    role = ("Watches the finished video frame by frame: empty or half-empty screens, text too small for a phone, pictures that stand "
            "still, scenes that miss the plan. Sends weak scenes back to be drawn again with the same voice.")

    def applies(self, ctx):
        media = ctx.outputs.get("media") or {}
        return bool(motion_cfg(ctx)["quality"] and media.get("path") and media.get("source", "crew") != "own"
                    and fr.have_ffmpeg())

    # ---------- looking ----------
    def look(self, ctx, media, scenes):
        work = Path(ctx.run.dir) / "quality"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        measures, cells = [], []
        for i, (a, b) in enumerate(spans(media, scenes), 1):
            shots = []
            for k, f in enumerate(SAMPLES):
                p = fr.grab(media["path"], a + (b - a) * f, work / f"s{i:02d}-{k}.png", 360)
                shots.append(p)
                cells.append((f"S{i}  {round(f * 100)}%", p))
            measures.append({"scene": i, "start": round(a, 2), "end": round(b, 2),
                             "frames": [fr.measure(p) for p in shots], "change": fr.change(shots[0], shots[-1])})
        sheets = [fr.sheet(cells[k:k + 12], work / f"sheet-{k // 12 + 1}.png", cols=4, cell_width=300) for k in range(0, len(cells), 12)]
        return measures, sheets

    def _report(self, scenes, measures, findings):
        lines = []
        for sc, m in zip(scenes, measures):
            d = sc.get("direction") or {}
            lines.append(f"SCENE {m['scene']} [{sc.get('part') or '-'}] {m['start']:.1f}-{m['end']:.1f}s layout {sc.get('layout')}\n"
                         f"  narration: {sc.get('narration', '')}\n"
                         f"  picture: { {k: sc.get(k) for k in ('on_screen', 'items', 'nodes', 'edges', 'code', 'cells') if sc.get(k)} }\n"
                         + (f"  director's plan: show {d.get('visual')}; focus {d.get('focus')}\n" if d.get("visual") else "")
                         + f"  measured: fill {m['frames'][0]['fill']:.3f}->{m['frames'][-1]['fill']:.3f}, height used "
                           f"{m['frames'][-1]['height']:.2f}, change {m['change']}")
        found = "\n".join(f"- {f['message']}" for f in findings) or "- none"
        return "\n".join(lines) + f"\n\nFOUND BY MEASURING (confirm on the sheets):\n{found}"

    # ---------- deciding ----------
    def run(self, ctx, guidance):
        script, media = ctx.outputs["writer"], ctx.outputs["media"]
        scenes = [dict(sc) for sc in script["scenes"]]
        mc = motion_cfg(ctx)
        L = lib.Library(ctx.ws)
        house = L.house()
        try:
            measures, sheets = self.look(ctx, media, scenes)
        except fr.FrameError as e:
            raise AgentError(f"could not look at the video: {e}")
        findings = picture_findings(measures, float(house["motion_language"].get("max_still_seconds", 3.5)) * 1.5)
        for f in findings:
            ctx.run.event(self.id, "found", f["message"], level="warning" if f["severity"] == "warn" else "error")
        review = None
        try:
            review = self.ask(ctx, self.prompt(ctx, house=L.brief()), self._report(scenes, measures, findings), SCHEMA,
                              images=[str(p) for p in sheets])
        except AgentError as e:
            if e.fatal:
                raise
            ctx.run.event(self.id, "no_vision", f"no vision review this time ({str(e)[:160]}): judged on the measurements only",
                          level="warning")
        errors = [f for f in findings if f["severity"] == "error"]
        if review:
            score = int(review["overall"])
        else:
            score = max(0, 100 - 25 * len(errors) - 6 * (len(findings) - len(errors)))
        if errors:
            score = min(score, 59)
        out = {"score": score, "scores": (review or {}).get("scores"), "summary": (review or {}).get("summary", ""),
               "findings": findings, "problems": [s["problem"] for s in (review or {}).get("scenes") or []],
               "measured": [{k: m[k] for k in ("scene", "change")} | {"fill": m["frames"][-1]["fill"], "height": m["frames"][-1]["height"]}
                            for m in measures],
               "sheets": [str(p) for p in sheets], "vision": bool(review), "redrawn": [], "held": False,
               "round": ctx.flags.get("quality_redraws", 0) + 1, "house_version": house.get("version", 0)}
        ctx.run.event(self.id, "scored", f"picture quality {score}/100" + (f": {out['summary'][:200]}" if out["summary"] else ""))
        weak = score < mc["min_score"] or errors
        # the script itself is wrong for its problem: no redraw can fix it, so the Script Writer writes it again (once per run)
        # never for a script the owner approved (a re-run that kept it): on 2026-11-06 the kept Diffie-Hellman script was sent back for how its
        # boxes were laid out, rewritten, and the run failed; a drawing problem is a redraw, and what still looks weak waits for the owner
        owner_ok = (ctx.outputs.get("editor") or {}).get("approved_by") == "owner"
        if weak and (review or {}).get("rewrite") and not ctx.flags.get("quality_rewrites") and not owner_ok:
            ctx.flags["quality_rewrites"] = 1
            out["rewrite"] = (review.get("rewrite_why") or out["summary"])[:600]
            ctx.run.event(self.id, "rewrite", f"picture quality {score}/100 and the script is wrong for its problem: back to the Script Writer: "
                                              f"{out['rewrite'][:200]}", level="warning")
            return out
        if weak and ctx.flags.get("quality_redraws", 0) < mc["max_redraws"]:
            fixes = [s for s in (review or {}).get("scenes") or [] if s.get("redraw")]
            g = GraphicsAgent()
            g.id = self.id   # its events are this agent's
            changed = g._apply(ctx, script, scenes, fixes)
            if changed:
                GraphicsAgent._complete(scenes)
                ctx.outputs["writer"] = finish(dict(script, scenes=scenes))
                ctx.flags["quality_redraws"] = ctx.flags.get("quality_redraws", 0) + 1
                out["redrawn"] = changed
                ctx.run.event(self.id, "redraw", f"scene(s) {', '.join(map(str, changed))} drawn again with the same voice")
                return out
        out["held"] = bool(score < mc["hold_below"] or errors)
        if out["held"]:
            ctx.run.event(self.id, "held", f"picture quality {score}/100: the video waits for your approval", level="warning")
        return out

    def validate(self, ctx, out):
        """A redraw is a send-back: the Supervisor draws the video again from the frame steps (the voice is reused). A rewrite goes back
        to the Script Writer."""
        if out.get("rewrite"):
            return [f"REWRITE: picture quality {out['score']}/100 and the script is wrong for its problem: {out['rewrite']}"] + \
                [p for p in out.get("problems", [])][:5]
        if out.get("redrawn"):
            return [f"picture quality {out['score']}/100: scene(s) {', '.join(map(str, out['redrawn']))} redesigned; "
                    f"draw the video again"] + [p for p in out.get("problems", [])][:5]
        return []

    def summary(self, out):
        if out.get("redrawn"):
            return f"picture {out['score']}/100: redrawing scene(s) {', '.join(map(str, out['redrawn']))}"
        notes = len(out.get("findings") or []) + len(out.get("problems") or [])
        return (f"picture {out['score']}/100" + ("" if out.get("vision") else " (measured only)")
                + (f", {notes} note(s)" if notes else ", looks right")
                + (": held for your approval" if out.get("held") else ""))
