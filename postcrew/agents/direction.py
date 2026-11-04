"""Creative Director (YouTube): turns the approved script into a visual plan before anything is drawn or voiced.

It runs after the Editor passes the script and before the Storyboard Artist. For every scene it decides what the scene is FOR (hook,
setup, explanation, example, reveal, summary, call to action), the one picture that shows the idea, the one thing the viewer must see, and
the beats that appear in the order the voice names them. It follows the house style (motion/library.py: the built-in rules, or the one
learned from your approved reference videos), the patterns that fit each scene, and every preference you approved.

It never changes the narration. Its notes travel with each scene (scene["direction"]); the Storyboard Artist draws to them and the Quality
Director judges the finished video against them. Problems a program can see are found first, for free: a long scene with nothing new to
show, the same layout three times in a row, too many words-only scenes, a hook that is only a title.

The Director only advises: if its model is unavailable the run goes on without notes rather than failing.
"""
from .. import platforms
from ..motion import library as lib
from .base import Agent, AgentError

LAYOUTS = ["title", "statement", "points", "code", "diagram", "trace", "flow", "stat", "codeviz", "paths", "grid"]
WORDS = ("title", "statement", "points")
PART_PURPOSE = {"problem": "hook", "approaches": "setup", "visual": "explanation", "conclusion": "summary", "idea": "explanation",
                "example": "example", "mistake": "reveal", "closing": "cta"}

NOTE = {"type": "object", "properties": {
    "scene": {"type": "integer", "description": "scene number, from 1"},
    "purpose": {"type": "string", "enum": lib.PURPOSES},
    "visual": {"type": "string", "description": "the one picture that shows this scene's idea, concretely (objects, data, a diagram)"},
    "focus": {"type": "string", "description": "the single thing the viewer must look at; it is highlighted"},
    "beats": {"type": "array", "items": {"type": "string"}, "maxItems": 6,
              "description": "what appears, in the order the voice names it; one beat every 2-4 seconds"},
    "layout": {"type": "string", "enum": LAYOUTS, "description": "the layout that draws this best"},
    "pattern": {"type": "string", "description": "the pattern used, by name, or empty"}},
    "required": ["scene", "purpose", "visual", "focus", "beats", "layout", "pattern"], "additionalProperties": False}
SCHEMA = {"type": "object", "properties": {
    "concept": {"type": "string", "description": "the visual thread of the whole video in one sentence (the picture that grows)"},
    "scenes": {"type": "array", "items": NOTE, "maxItems": 60},
    "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 6}},
    "required": ["concept", "scenes", "risks"], "additionalProperties": False}


def motion_cfg(ctx):
    m = (ctx.cfg.get("video") or {}).get("motion") or {}
    return {"director": m.get("director", True), "quality": m.get("quality", True), "min_score": int(m.get("min_score", 75)),
            "max_redraws": int(m.get("max_redraws", 1)), "hold_below": int(m.get("hold_below", 60))}


def scene_seconds(sc):
    words = len((sc.get("narration") or "").split())
    return words / platforms.WORDS_PER_SECOND if words else float(sc.get("seconds") or 0)


def plan_problems(scenes, house):
    """What a program can see in the plan before anything is drawn: [(scene number or 0, message)]."""
    out = []
    still = float(house.get("motion_language", {}).get("max_still_seconds", 3.5))
    run = 1
    for i, sc in enumerate(scenes, 1):
        lay, secs = sc.get("layout"), scene_seconds(sc)
        if sc.get("part") == "closing":
            continue
        if lay in WORDS:
            things = len(sc.get("items") or []) + 1
            if secs / things > still * 2:
                out.append((i, f"scene {i}: {secs:.0f}s of voice over a words-only picture with {things} thing(s) to show: "
                               f"give it a picture with a new beat every {still:.0f}s"))
        if i > 1 and lay == scenes[i - 2].get("layout") and lay not in ("codeviz",):
            run += 1
            if run == 3:
                out.append((i, f"scene {i}: the third {lay} scene in a row: vary the picture"))
        else:
            run = 1
    body = [s for s in scenes if s.get("part") != "closing"]
    if body and sum(1 for s in body if s.get("layout") in WORDS) > len(body) / 3:
        out.append((0, f"{sum(1 for s in body if s.get('layout') in WORDS)} of {len(body)} scenes are words only: at most a third may be"))
    if scenes and scenes[0].get("layout") == "title" and not scenes[0].get("clip"):
        out.append((1, "scene 1: the hook is a title card: show the problem as a picture in the first 2 seconds"))
    return out


class CreativeDirectorAgent(Agent):
    id = "direction"
    title = "Creative Director"
    name = "Muse"
    role = ("Plans the picture of every scene before anything is drawn: its purpose, the one visual that shows the idea, what the viewer "
            "must see and the beats in spoken order, in the house style learned from your reference videos.")

    def applies(self, ctx):
        from .. import assets as assets_mod
        if not motion_cfg(ctx)["director"]:
            return False
        if "video" in assets_mod.find(ctx.ws, ctx.platform, ctx.day):   # the owner's own finished video: nothing to direct
            return False
        from .graphics import GraphicsAgent
        return GraphicsAgent().applies(ctx)   # its notes are drawn by the Storyboard Artist (Remotion videos)

    def _report(self, ctx, scenes, L, findings):
        lines = []
        for i, sc in enumerate(scenes, 1):
            purpose = PART_PURPOSE.get(sc.get("part"), "explanation")
            pats = L.relevant_patterns(purpose, sc.get("narration", ""))
            now = {k: sc.get(k) for k in ("layout", "on_screen", "items", "nodes", "edges") if sc.get(k)}
            lines.append(f"SCENE {i} [{sc.get('part') or '-'}] about {scene_seconds(sc):.0f}s\n  narration: {sc.get('narration', '')}\n"
                         f"  picture now: {now}" + ("\n  patterns that fit: " + "; ".join(f"{p['name']}: {p['recipe']}" for p in pats) if pats else ""))
        found = "\n".join(f"- {m}" for _n, m in findings) or "- none"
        return "\n".join(lines) + f"\n\nFOUND BY THE PROGRAM (fix these in your plan):\n{found}"

    def run(self, ctx, guidance):
        script = ctx.outputs["writer"]
        scenes = [dict(sc) for sc in script["scenes"]]
        L = lib.Library(ctx.ws)
        house = L.house()
        findings = plan_problems(scenes, house)
        for _n, m in findings:
            ctx.run.event(self.id, "found", m, level="warning")
        try:
            plan = self.ask(ctx, self.prompt(ctx, house=L.brief()), self._report(ctx, scenes, L, findings), SCHEMA)
        except AgentError as e:
            if e.fatal:
                raise
            ctx.run.event(self.id, "skipped", f"no visual plan this time ({str(e)[:160]}): the Storyboard Artist works without notes",
                          level="warning")
            return {"concept": "", "notes": 0, "findings": [m for _n, m in findings], "house_version": house.get("version", 0),
                    "skipped": str(e)[:200]}
        notes = 0
        for n in plan.get("scenes") or []:
            k = n.get("scene", 0)
            if not 1 <= k <= len(scenes) or scenes[k - 1].get("part") == "closing":
                continue
            scenes[k - 1]["direction"] = {x: n.get(x) for x in ("purpose", "visual", "focus", "beats", "layout", "pattern")}
            notes += 1
        ctx.outputs["writer"] = dict(script, scenes=scenes, concept=plan.get("concept", ""))
        ctx.run.event(self.id, "planned", f"{notes} scene(s) directed; concept: {plan.get('concept', '')[:160]}")
        return {"concept": plan.get("concept", ""), "notes": notes, "risks": plan.get("risks") or [],
                "findings": [m for _n, m in findings], "house_version": house.get("version", 0), "house": house.get("profile_name")}

    def summary(self, out):
        if out.get("skipped"):
            return "no visual plan (model unavailable); drawn without notes"
        return (f"{out['notes']} scene(s) directed in {out.get('house') or 'the house style'} v{out.get('house_version', 0)}"
                + (f"; {len(out['findings'])} plan problem(s) handed to the Storyboard Artist" if out.get("findings") else ""))
