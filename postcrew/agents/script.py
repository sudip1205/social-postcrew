"""Script Writer (YouTube): turns the topic and verified research into the whole video script: title, description, tags,
thumbnail text and the scenes (what the voice says, what is on screen).

It is the Writer of the YouTube crew (same id, so the supervisor, the writer team, the Editor's fixes, memory and per-agent
model settings all work as for LinkedIn). A team of writers drafts, every draft passes the automatic checks (checks.
script_problems), is pre-reviewed and polished, and only the best goes to the Editor: exactly the LinkedIn writer's loop.

A script the owner supplies (assets.py) skips the drafting; it is parsed, completed with metadata and validated and reviewed
like any other.
"""
import json
import re

from .. import assets as assets_mod
from .. import brief as briefmod
from .. import algotrace, codeviz, graphviz, gridviz, pathviz, platforms, shapes
from .. import checks as checks_mod
from ..checks import PARTS, repeat_problem, script_problems
from . import team
from .base import AgentError, algorithm_mode, guidance_block, recent_block
from .writer import WriterAgent, research_block

STEP = {
    "type": "object",
    "properties": {
        "say": {"type": "string", "description": "two or three words of the narration, said just as this step happens"},
        "pointers": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                     "description": "where each pointer is now, 'left=0', 'right=3' (name=cell position, counted from 0)"},
        "active": {"type": "array", "items": {"type": "integer"}, "description": "cells being looked at now"},
        "found": {"type": "array", "items": {"type": "integer"}, "description": "cells that are the answer"},
        "out": {"type": "array", "items": {"type": "integer"}, "description": "cells already ruled out"},
        "note": {"type": "string", "description": "the sum or the decision, at most 60 characters: '2 + 15 = 17, too big'"},
        "memo": {"type": "array", "items": {"type": "string"}, "maxItems": 6,
                 "description": "what is remembered at this step (a hash map, a visited set): ['2 -> 0', '7 -> 1']"},
    },
    "required": ["say", "pointers", "active", "found", "out", "note", "memo"],
    "additionalProperties": False,
}
SCENE = {
    "type": "object",
    "properties": {
        "layout": {"type": "string", "enum": ["title", "statement", "points", "code", "diagram", "trace", "flow", "stat", "codeviz", "paths", "grid", "graph", "run"]},
        "part": {"type": "string", "enum": list(PARTS),
                 "description": "which part of the video this scene is: intro (a short opening), problem (what is asked, with an example input and answer), visual (the idea drawn in plain words: the smallest case or first step first, then the next), conclusion (the pattern the pictures showed), approaches (the ways it can be solved, compared, no code yet), idea (the chosen solution), example (worked example: code only for an algorithm or a coding solution), mistake (a common mistake to avoid), closing (the like, comment, share card)"},
        "narration": {"type": "string", "description": "what the voice says; spoken sentences, no markdown"},
        "on_screen": {"type": "string", "description": "the key words shown big (or the heading above the points)"},
        "items": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "code": {"type": "string"}, "language": {"type": "string"},
        "nodes": {"type": "array", "items": {"type": "string"}, "maxItems": 6,
                  "description": "diagram: the boxes, 2-6 short labels (at most 18 characters), optionally with an icon: 'API Gateway|gateway'"},
        "edges": {"type": "array", "items": {"type": "string"}, "maxItems": 8,
                  "description": "diagram: arrows in the order the voice explains them, 'Client > Load Balancer: request'"},
        "cells": {"type": "array", "items": {"type": "string"}, "maxItems": 10,
                  "description": "trace: the example data, e.g. an array: ['2','7','11','15'] (at most 6 characters each)"},
        "steps": {"type": "array", "maxItems": 12, "items": STEP,
                  "description": "trace: what happens to the data, one entry per move, in the order the voice says it"},
        "viz": codeviz.VIZ,
        "paths": pathviz.PATHS,
        "grid": gridviz.GRID,
        "graph": graphviz.GRAPH,
        "run": algotrace.RUN,
        "seconds": {"type": "number"},
    },
    "required": ["layout", "part", "narration", "on_screen", "items", "code", "language", "nodes", "edges", "cells", "steps", "seconds"],   # viz: only a codeviz scene has one
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"}, "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 15},
        "thumbnail_text": {"type": "string"},
        "scenes": {"type": "array", "items": SCENE, "maxItems": 60},
    },
    "required": ["title", "description", "tags", "thumbnail_text", "scenes"],
    "additionalProperties": False,
}

FORMAT_RULES = {
    "short": "A vertical 9:16 Short of at most 60 seconds: a short opening, the problem with an example, the idea named and defined with its picture, then how it works shown as a diagram with one example moving through it (code only for an algorithm problem).",
    "long": "A 16:9 video: open with a short introduction (about 15 seconds), state the problem, lay out the ways to solve it, then one idea per scene (about 4-12 scenes per ten minutes), "
            "and finish with one clear next step.",
}


def script_revision_block(ctx, guidance, prev=None):
    """A script sent back is revised from the WHOLE previous script (every scene with its picture), so a fix to one scene does not re-invent the rest."""
    prev = prev or ctx.previous.get("writer")
    if not (guidance and prev and prev.get("scenes")):
        return ""
    keep = {k: prev.get(k) for k in ("title", "description", "tags", "thumbnail_text")}
    keep["scenes"] = [{k: sc.get(k) for k in ("layout", "part", "narration", "on_screen", "items", "code", "language", "nodes", "edges", "cells", "steps", "viz", "paths", "grid", "graph", "run") if sc.get(k) not in (None, "", [])}
                      for sc in prev["scenes"]]
    return ("\n\nYOUR PREVIOUS SCRIPT was sent back. REVISE it: keep every scene that is fine exactly as it is, and change only what the points below require "
            "(the picture fields of a scene you do not touch stay as they are). Do not add new claims while fixing.\n<previous_script>\n"
            + json.dumps(keep, ensure_ascii=False, indent=1) + "\n</previous_script>")


CALC = __import__("re").compile(r"\b(adding|add|gives|makes|plus|minus .{0,12}\bis|the larger of|the smaller of|beats|subtract\w*)\b", __import__("re").I)


def algorithm_problems(script):
    scenes = script.get("scenes") or []
    hand = [i for i, sc in enumerate(scenes, 1) if (sc.get("layout") in ("trace", "codeviz") and (sc.get("steps") or sc.get("viz")))
            or (sc.get("layout") == "grid" and (sc.get("grid") or {}).get("steps"))]
    out = []
    if hand:
        out.append(f"scene(s) {', '.join(map(str, hand))}: this is an algorithm video, so a walk-through is a 'run' scene (the app runs your code "
                   f"and draws its real steps), never trace, grid or codeviz steps written by hand. Turn each into a run scene")
    if sum(1 for sc in scenes if sc.get("layout") == "run") < 2:
        out.append("an algorithm video needs at least two 'run' scenes: the simple way run step by step, and the better way run step by step")
    # a calculation on the example is SHOWN, by the code running: never narrated over a diagram or words
    calc = [i for i, sc in enumerate(scenes, 1) if sc.get("layout") not in ("run", "code", "points") and sc.get("part") != "closing"
            and len(CALC.findall(str(sc.get("narration") or ""))) >= 2]
    if calc:
        out.append(f"scene(s) {', '.join(map(str, calc))} narrate calculations on the example ('adding gives', 'the larger of') over a picture that "
                   f"does not compute them: in an algorithm video every calculation is a 'run' scene, where the app runs the code and shows it")
    # the simple way first: the run scenes go from the most nested loops (brute force) to the fewest, the mistake aside
    from .. import fidelity
    runs = [(i, fidelity.loop_depth(sc.get("code"))) for i, sc in enumerate(scenes, 1) if sc.get("layout") == "run" and sc.get("part") != "mistake"]
    if runs and runs[0][1] < max(d for _, d in runs):
        out.append(f"the first walk-through (scene {runs[0][0]}) runs a faster way before the simple one: run the simple way (brute force, scene "
                   f"{next(i for i, d in runs if d == max(d_ for _, d_ in runs))}) first, see why it is slow, then the idea and the better way run")
    first_run = runs[0][0] if runs else len(scenes) + 1
    early = [i for i, sc in enumerate(scenes[:first_run - 1], 1) if sc.get("part") in ("visual", "conclusion")]
    if early:
        out.append(f"scene(s) {', '.join(map(str, early))} teach the idea before any code has run: in an algorithm video the order is the problem on "
                   f"its example, the simple way RUN step by step (its run scenes are the 'visual' part), why it is slow, then the idea, the better "
                   f"way run, its code, the mistake run")
    return out


def finish(script):
    """Make the parts agree: the voice-over is the scenes' narration in order, every scene has a length."""
    scenes = []
    for sc in script.get("scenes") or []:
        sc = dict(sc)
        sc["narration"] = " ".join((sc.get("narration") or "").split())
        sc["items"] = [i for i in sc.get("items") or [] if i]
        sc["nodes"] = [n.strip() for n in sc.get("nodes") or [] if n and n.strip()]
        sc["edges"] = [e.strip() for e in sc.get("edges") or [] if e and e.strip()]
        sc["cells"] = [str(c).strip() for c in sc.get("cells") or [] if str(c).strip()]
        sc["steps"] = [st for st in sc.get("steps") or [] if isinstance(st, dict)]
        words = len(sc["narration"].split())
        sc["seconds"] = round(words / platforms.WORDS_PER_SECOND, 1) if words else 0
        scenes.append(sc)
    return dict(script, scenes=scenes, text="\n\n".join(s["narration"] for s in scenes if s["narration"]))


class ScriptWriter(WriterAgent):
    id = "writer"
    title = "Script Writer"
    name = "Script team"
    role = "Writes the whole video script (hook, scenes, title, description, tags) from verified facts only."

    def run(self, ctx, guidance):
        own = assets_mod.find(ctx.ws, ctx.platform, ctx.day).get("script")
        if own and not guidance:
            return self._own(ctx, own)
        out = super().run(ctx, guidance)
        out["source"] = "crew"
        return out

    # ---------- the owner's script ----------
    def _own(self, ctx, path):
        try:
            script = assets_mod.read_script(path)
        except assets_mod.AssetError as e:
            raise AgentError(f"your script file: {e}", fatal=True)
        topic = ctx.outputs.get("topic") or {}
        cat = ctx.cat
        words = script["text"].split()
        script["title"] = script["title"] or topic.get("topic") or " ".join(words[:9])
        if len(script["title"]) < 10:
            script["title"] = f"{script['title']}: {topic.get('angle', '')}"[:100].strip(": ")
        sentences = [s for s in script["text"].replace("\n", " ").split(". ") if s.strip()]
        script["description"] = script["description"] or (
            (topic.get("angle") + "\n\n" if topic.get("angle") else "") + ". ".join(sentences[:3]).strip(". ") + ".\n\n"
            "Questions? Ask in the comments.")
        if not script["tags"]:
            keys = [w.strip(".,:;!?()").lower() for w in (script["title"] + " " + (topic.get("topic") or "")).split()]
            script["tags"] = list(dict.fromkeys(w for w in keys if len(w) > 3))[:8] or [cat.get("kicker", "tutorial").lower()]
        while len(script["tags"]) < 3:
            script["tags"].append(f"{cat.get('kicker', 'tech').lower()} tips"[: 30])
        script["thumbnail_text"] = script["thumbnail_text"] or " ".join(script["title"].split()[:3])[:30]
        ctx.run.event(self.id, "own_script", f"using your script ({len(words)} words, {len(script['scenes'])} scenes)")
        return dict(finish(script), source="own", author="owner", author_name="You")

    # ---------- the crew's draft ----------
    def _draft(self, ctx, guidance, member, prev=None):
        topic, spec = ctx.outputs["topic"], ctx.video
        lo, hi = spec.get("min_words", int(spec["max_words"] * 0.7)), spec["max_words"]
        system = (self.prompt(ctx, format=spec["format"], target_seconds=spec["target_seconds"], min_words=lo, max_words=hi,
                              format_rules=FORMAT_RULES[spec["format"]], wps=spec.get("wps", 2.5), outro=spec.get("outro") or "(none: end with one clear next step)",
                              shorts_rule="Do not write #Shorts yourself: the app adds it to Shorts.",
                              short_max_words=(checks_mod.short_max_words() if spec["format"] == "short" else "no limit"))
                  + team.persona_block(ctx.ws, member))
        notes = briefmod.cat_context(ctx.cat)
        if platforms.renderer_for(ctx.cfg, ctx.category) in ("blackboard", "explainer"):
            notes += ("\nHOW IT IS SHOWN: animated while the voice talks. One diagram that keeps growing: reuse the same box "
                      "labels in consecutive diagram scenes. Name each box in the narration at the moment it should appear and "
                      "explain the arrows in the order they are listed; keep on_screen titles and labels to a few words.")
        prompt = (f"Category: {ctx.cat['label']}\nWhat this category needs: {ctx.cat['brief']}\n"
                  + (notes + "\n" if notes else "")
                  + f"Video: {spec['format']}, guide length about {spec['target_seconds']} seconds (a guide only: take the time the topic needs)\n"
                  f"Topic: {topic['topic']}\nAngle: {topic['angle']}\n\n"
                  + research_block(ctx.outputs.get("research"))
                  + f"\n\nRecent videos (do not repeat their hook or structure):\n{recent_block(ctx, 6)}"
                  + script_revision_block(ctx, guidance, prev)
                  + guidance_block(guidance))
        return finish(self.ask(ctx, system, prompt, SCHEMA, member=member))

    def validate(self, ctx, out):
        spec = ctx.video
        if out.get("source") == "own":   # the owner's own length is what it is; a Short still has to fit in a minute
            words = len(out["text"].split())
            spec = dict(spec, target_seconds=max(15, round(words / platforms.WORDS_PER_SECOND)), max_words=max(words, 1), min_words=0)
            problems = script_problems(out, spec, ctx.cat, ctx.profile)
            if spec["format"] == "short" and words / platforms.WORDS_PER_SECOND > platforms.SHORT_MAX_S + 3:
                problems.append(f"your script runs about {words / platforms.WORDS_PER_SECOND:.0f} seconds: too long for a "
                                f"Short (1 minute at most). Cut it or make a long video")
            return problems
        problems = script_problems(out, spec, ctx.cat, ctx.profile)
        problems += shapes.scene_problems(ctx, out)   # a problem's data drawn as its own shape (a grid as a grid)
        plan = (ctx.outputs.get("topic") or {}).get("owner_plan") or {}
        problems += shapes.example_problems(ctx, out, {"examples": plan.get("examples")} if plan.get("examples") else None)
        dup = repeat_problem("", out.get("text", ""), ctx.recent(60))
        if dup:
            problems.append(dup)
        research = ctx.outputs.get("research") or {}
        if ctx.cat.get("research") == "required" and not research.get("verified"):
            problems.append("this category needs verified sources: ask for research first")
        if ctx.cat.get("fact_check"):
            from ..checks import number_problems
            verified = [dict(s, page=research.get("_pages", {}).get(s["url"], "")) for s in research.get("verified", [])]
            problems += number_problems(out["text"] + " " + out.get("title", ""), "", verified + briefmod.supplied(ctx))
        if algorithm_mode(ctx):   # an algorithm video: every walk-through is the code RUN, never steps typed by hand
            problems += algorithm_problems(out)
        return problems

    def summary(self, out):
        t = out.get("text", "")
        who = f"by {out['author_name']}" if out.get("author_name") else ""
        if len(out.get("team", [])) > 1:
            who += f" (best of {len(out['team'])})"
        if out.get("pre_review"):
            who += f", pre-review {out['pre_review']['overall']}"
        return (f"'{out.get('title', '')[:50]}': {len(out.get('scenes', []))} scenes, {len(t.split())} words "
                f"(~{len(t.split()) / platforms.SPOKEN_WPS:.0f}s voiced) {who}")
