"""Script Writer (YouTube): turns the topic and verified research into the whole video script: title, description, tags,
thumbnail text and the scenes (what the voice says, what is on screen).

It is the Writer of the YouTube crew (same id, so the supervisor, the writer team, the Editor's fixes, memory and per-agent
model settings all work as for LinkedIn). A team of writers drafts, every draft passes the automatic checks (checks.
script_problems), is pre-reviewed and polished, and only the best goes to the Editor: exactly the LinkedIn writer's loop.

A script the owner supplies (assets.py) skips the drafting; it is parsed, completed with metadata and validated and reviewed
like any other.
"""
from .. import assets as assets_mod
from .. import brief as briefmod
from .. import platforms
from ..checks import repeat_problem, script_problems
from . import team
from .base import AgentError, guidance_block, recent_block
from .writer import WriterAgent, research_block, revision_block

SCENE = {
    "type": "object",
    "properties": {
        "layout": {"type": "string", "enum": ["title", "statement", "points", "code", "diagram"]},
        "narration": {"type": "string", "description": "what the voice says; spoken sentences, no markdown"},
        "on_screen": {"type": "string", "description": "the key words shown big (or the heading above the points)"},
        "items": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "code": {"type": "string"}, "language": {"type": "string"},
        "nodes": {"type": "array", "items": {"type": "string"}, "maxItems": 6,
                  "description": "diagram: the boxes, 2-6 short labels (at most 18 characters)"},
        "edges": {"type": "array", "items": {"type": "string"}, "maxItems": 8,
                  "description": "diagram: arrows in the order the voice explains them, 'Client > Load Balancer: request'"},
        "seconds": {"type": "number"},
    },
    "required": ["layout", "narration", "on_screen", "items", "code", "language", "nodes", "edges", "seconds"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"}, "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 15},
        "thumbnail_text": {"type": "string"},
        "scenes": {"type": "array", "items": SCENE, "maxItems": 40},
    },
    "required": ["title", "description", "tags", "thumbnail_text", "scenes"],
    "additionalProperties": False,
}

FORMAT_RULES = {
    "short": "A vertical 9:16 Short: 3-8 scenes, one idea, the hook inside the first 3 seconds, under 60 seconds in all.",
    "long": "A 16:9 video: open with a 15-second cold open, then one idea per scene (about 4-12 scenes per ten minutes), "
            "and finish with one clear next step.",
}


def finish(script):
    """Make the parts agree: the voice-over is the scenes' narration in order, every scene has a length."""
    scenes = []
    for sc in script.get("scenes") or []:
        sc = dict(sc)
        sc["narration"] = " ".join((sc.get("narration") or "").split())
        sc["items"] = [i for i in sc.get("items") or [] if i]
        sc["nodes"] = [n.strip() for n in sc.get("nodes") or [] if n and n.strip()]
        sc["edges"] = [e.strip() for e in sc.get("edges") or [] if e and e.strip()]
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
        lo, hi = int(spec["max_words"] * 0.7), spec["max_words"]
        system = (self.prompt(ctx, format=spec["format"], target_seconds=spec["target_seconds"], min_words=lo, max_words=hi,
                              format_rules=FORMAT_RULES[spec["format"]],
                              shorts_rule="Do not write #Shorts yourself: the app adds it to Shorts.")
                  + team.persona_block(ctx.ws, member))
        notes = briefmod.cat_context(ctx.cat)
        if platforms.renderer_for(ctx.cfg, ctx.category) == "blackboard":
            notes += ("\nHOW IT IS SHOWN: drawn by hand on a blackboard while the voice talks. Use diagram scenes for flows and "
                      "structures; name each box in the narration at the moment it should appear and explain the arrows in "
                      "the order they are drawn; keep on_screen and labels to a few words.")
        prompt = (f"Category: {ctx.cat['label']}\nWhat this category needs: {ctx.cat['brief']}\n"
                  + (notes + "\n" if notes else "")
                  + f"Video: {spec['format']}, about {spec['target_seconds']} seconds ({lo}-{hi} words of narration)\n"
                  f"Topic: {topic['topic']}\nAngle: {topic['angle']}\n\n"
                  + research_block(ctx.outputs.get("research"))
                  + f"\n\nRecent videos (do not repeat their hook or structure):\n{recent_block(ctx, 6)}"
                  + revision_block(ctx, guidance, prev)
                  + guidance_block(guidance))
        return finish(self.ask(ctx, system, prompt, SCHEMA, member=member))

    def validate(self, ctx, out):
        spec = ctx.video
        if out.get("source") == "own":   # the owner's own length is what it is; a Short still has to fit in a minute
            words = len(out["text"].split())
            spec = dict(spec, target_seconds=max(15, round(words / platforms.WORDS_PER_SECOND)), max_words=max(words, 1))
            problems = script_problems(out, spec, ctx.cat, ctx.profile)
            if spec["format"] == "short" and words / platforms.WORDS_PER_SECOND > 63:
                problems.append(f"your script runs about {words / platforms.WORDS_PER_SECOND:.0f} seconds: too long for a "
                                f"Short (60 s at most). Cut it or make a long video")
            return problems
        problems = script_problems(out, spec, ctx.cat, ctx.profile)
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
        return problems

    def summary(self, out):
        t = out.get("text", "")
        who = f"by {out['author_name']}" if out.get("author_name") else ""
        if len(out.get("team", [])) > 1:
            who += f" (best of {len(out['team'])})"
        if out.get("pre_review"):
            who += f", pre-review {out['pre_review']['overall']}"
        return f"'{out.get('title', '')[:50]}': {len(out.get('scenes', []))} scenes, {len(t.split())} words (~{len(t.split()) / 2.5:.0f}s) {who}"
