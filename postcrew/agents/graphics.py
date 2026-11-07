"""Storyboard Artist (YouTube): designs the picture of every scene of the approved script, with real icons and cliparts.

It runs after the Editor has passed the script and before anything is voiced or drawn. The narration is never changed: only what
is on screen. For every scene it sees the narration and, for every box and every idea, icons found in the free catalog
(render/iconlib.py: Lucide, product logos, brand marks and flat cliparts). It may turn a words-only scene into a diagram or flow, name
the icon of each box (logos:redis for Redis, lucide:network for a load balancer) and choose the clipart that stands for a scene's idea.

The rules are tight and kept by the program, not hoped for: every box ends with an icon, every words scene (statement, points, title)
ends with a clipart, a replacement that breaks a script rule is left out, and no more than a third of the scenes may be words only.
"""
import re

from .. import platforms
from ..checks import STOP_WORDS, script_problems, split_long_scenes, storyboard_problems
from ..render import iconlib
from ..render.scenes import split_node
from .base import Agent, AgentError
from .script import STEP, finish

LAYOUTS = ["title", "statement", "points", "code", "diagram", "trace", "flow", "stat"]
VISUAL_KEYS = ("layout", "on_screen", "items", "nodes", "edges", "code", "language", "cells", "steps", "clip")
PLAIN = ("title", "statement", "points")
FIX = {
    "type": "object",
    "properties": {
        "scene": {"type": "integer", "description": "scene number, from 1"},
        "why": {"type": "string", "description": "what was wrong with the picture, in one sentence"},
        "layout": {"type": "string", "enum": LAYOUTS},
        "on_screen": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "nodes": {"type": "array", "items": {"type": "string"}, "maxItems": 6,
                  "description": "diagram or flow: 'Label|set:name' (label at most 18 characters, the icon from the catalog, e.g. 'Cache|logos:redis')"},
        "edges": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "code": {"type": "string"}, "language": {"type": "string"},
        "cells": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "steps": {"type": "array", "items": STEP, "maxItems": 12},
        "clip": {"type": "string", "description": "title, statement or points: the clipart beside the words, 'set:name' from the catalog; '' otherwise"},
    },
    "required": ["scene", "why", *VISUAL_KEYS],
    "additionalProperties": False,
}
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}, "scenes": {"type": "array", "items": FIX, "maxItems": 60}},
          "required": ["summary", "scenes"], "additionalProperties": False}
CLIP_SETS = ("fluent-emoji-flat", "lucide")


def concepts(scene):
    """The words that say what a scene is about: its heading first, then the narration's longer words."""
    words = re.findall(r"[a-zA-Z]{4,}", f"{scene.get('on_screen', '')} {scene.get('narration', '')}")
    seen, out = set(), []
    for w in words:
        lw = w.lower()
        if lw not in STOP_WORDS and lw not in seen:
            seen.add(lw)
            out.append(lw)
    return out[:14]


def clip_candidates(scene, limit=8):
    out, seen = [], set()
    for w in concepts(scene):
        for h in iconlib.search(w, 2, CLIP_SETS):
            if h["id"] not in seen:
                seen.add(h["id"])
                out.append(h["id"])
    return out[:limit]


def label_of(node):
    return split_node(node)[0]


def with_icon(node):
    """'Cache' -> 'Cache|lucide:zap' (the best match for the label) unless it already names an icon that exists."""
    label, hint = split_node(node)
    if hint and iconlib.get(hint):
        return node
    guess = iconlib.auto(label)
    return f"{label}|{guess}" if guess else label


class GraphicsAgent(Agent):
    id = "graphics"
    title = "Storyboard Artist"
    name = "Sketch"
    role = ("Designs every scene's picture from the approved script with real icons and cliparts from a free catalog: diagrams with an icon on "
            "every box, a clipart beside every words scene. Never touches the narration.")

    def applies(self, ctx):
        return (ctx.video.get("renderer") == "remotion" and bool((ctx.cfg.get("video") or {}).get("graphics", True)) and iconlib.available())

    # ---------- what the artist is shown ----------
    @staticmethod
    def _report(scenes, spec):
        wps = float(spec.get("wps") or 2.5)
        lines = []
        for i, sc in enumerate(scenes, 1):
            secs = len((sc.get("narration") or "").split()) / wps
            now = {k: sc.get(k) for k in VISUAL_KEYS if sc.get(k)}
            lines.append(f"SCENE {i} [{sc.get('part') or '-'}] about {secs:.0f}s\n  narration: {sc.get('narration', '')}\n  picture now: {now}")
            d = sc.get("direction") or {}
            if d.get("visual"):   # the Creative Director's plan for this scene
                lines.append(f"    DIRECTOR: {d.get('purpose', '')}; show {d['visual']}; focus on {d.get('focus', '')}; "
                             f"beats: {' > '.join(d.get('beats') or [])}; layout {d.get('layout', '')}")
            for n in sc.get("nodes") or []:
                label = label_of(n)
                lines.append(f"    icons for box '{label}': {', '.join(h['id'] for h in iconlib.search(label, 5)) or '(none found: pick one yourself)'}")
            if sc.get("layout") in PLAIN and sc.get("part") != "closing":
                lines.append(f"    clipart ideas: {', '.join(clip_candidates(sc)) or '(search the catalog yourself)'}")
        return "\n".join(lines)

    # ---------- applying it, checked ----------
    def _apply(self, ctx, script, scenes, fixes):
        changed, spec = [], ctx.video
        for f in fixes:
            n = f["scene"]
            if not 1 <= n <= len(scenes) or scenes[n - 1].get("part") == "closing" or scenes[n - 1].get("layout") in ("codeviz", "paths", "grid", "graph", "run"):   # drawn from its own numbers
                continue
            old = scenes[n - 1]
            new = dict(old, **{k: f.get(k, old.get(k)) for k in VISUAL_KEYS})   # the narration is never in the replacement
            new["items"] = [x for x in new.get("items") or [] if x][:5]
            if new.get("clip") and not iconlib.get(new["clip"]):
                new["clip"] = ""
            new["nodes"] = [with_icon(x) for x in new.get("nodes") or []]
            if all(new.get(k) == old.get(k) for k in VISUAL_KEYS):
                continue
            trial = scenes[:n - 1] + [new] + scenes[n:]
            keep = lambda sc_list: {p for p in script_problems(finish(dict(script, scenes=sc_list)), spec, ctx.cat, ctx.profile)
                                    if p.startswith(f"scene {n}:")}
            if keep(trial) - keep(scenes):
                ctx.run.event(self.id, "rejected_fix", f"scene {n}: the new picture breaks a rule ({sorted(keep(trial) - keep(scenes))[0]}); kept as it was",
                              level="warning")
                continue
            scenes[n - 1] = new
            changed.append(n)
        return changed

    @staticmethod
    def _complete(scenes):
        """What the program guarantees whatever the model did: an icon on every box, a clipart on every words scene."""
        boxes = clips = 0
        for sc in scenes:
            if sc.get("layout") in ("diagram", "flow"):
                sc["nodes"] = [with_icon(n) for n in sc.get("nodes") or []]
                boxes += sum(1 for n in sc["nodes"] if split_node(n)[1])
            elif sc.get("layout") in PLAIN and sc.get("part") != "closing":
                if not (sc.get("clip") and iconlib.get(sc["clip"])):
                    pick = clip_candidates(sc, 1)
                    sc["clip"] = pick[0] if pick else ""
                clips += 1 if sc.get("clip") else 0
        return boxes, clips

    def run(self, ctx, guidance):
        script = ctx.outputs["writer"]
        scenes = split_long_scenes([dict(sc) for sc in script["scenes"]], ctx.video)   # a scene that talks too long becomes several: each gets its own picture
        if len(scenes) != len(script["scenes"]):
            ctx.run.event(self.id, "split", f"{len(scenes) - len(script['scenes'])} long scene(s) split so every picture matches its words")
        review = self.ask(ctx, self.prompt(ctx), self._report(scenes, ctx.video), SCHEMA)
        changed = self._apply(ctx, script, scenes, review.get("scenes") or [])
        boxes, clips = self._complete(scenes)
        ctx.outputs["writer"] = finish(dict(script, scenes=scenes))
        kinds = {}
        for sc in scenes:
            kinds[sc.get("layout")] = kinds.get(sc.get("layout"), 0) + 1
        ctx.run.event(self.id, "designed", f"{len(changed)} scene(s) redesigned; {boxes} icons on boxes, {clips} cliparts; pictures: "
                      + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())))
        return {"changed": changed, "icons": boxes, "cliparts": clips, "layouts": kinds, "summary": review.get("summary", "")}

    def validate(self, ctx, out):
        scenes = ctx.outputs["writer"]["scenes"]
        problems = []
        for i, sc in enumerate(scenes, 1):
            if sc.get("layout") in ("diagram", "flow") and any(not split_node(n)[1] or not iconlib.get(split_node(n)[1]) for n in sc.get("nodes") or []):
                problems.append(f"scene {i}: a box has no icon from the catalog")
        problems += [p for p in storyboard_problems(scenes, ctx.video) if "only words" in p or "in a row" in p]
        return problems

    def summary(self, out):
        return (f"{len(out['changed'])} scene(s) redesigned, {out['icons']} icons, {out['cliparts']} cliparts" if out else "")
