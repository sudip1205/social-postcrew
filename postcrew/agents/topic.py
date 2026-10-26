"""Topic agent: decides what today's post is about, from the day's category and what was posted before."""
from datetime import timedelta

from .. import brief as briefmod
from ..checks import repeat_problem
from ..render import tracers
from .base import Agent, AgentError, guidance_block, recent_block
from .planner import planned_for

SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "description": "Short topic name, 5-90 chars (used to detect repeats)"},
        "angle": {"type": "string", "description": "The specific take: what the reader will learn or be able to do"},
        "why_now": {"type": "string", "description": "Why this is timely or useful this week"},
        "search_queries": {"type": "array", "items": {"type": "string"}, "maxItems": 5,
                           "description": "Queries the research agent should run (empty if no research)"},
    },
    "required": ["topic", "angle", "why_now", "search_queries"],
    "additionalProperties": False,
}


_SYSTEM = {"type": "object", "required": ["id", "label", "kind"], "additionalProperties": False,
           "properties": {"id": {"type": "string"}, "label": {"type": "string"},
                          "kind": {"type": "string", "enum": briefmod.COMPONENT_KINDS}, "note": {"type": "string"}}}
_STEP = {"type": "object", "required": ["from", "to", "label"], "additionalProperties": False,
         "properties": {"from": {"type": "string"}, "to": {"type": "string"}, "label": {"type": "string"},
                        "kind": {"type": "string", "enum": briefmod.STEP_KINDS}, "payload": {"type": "string"},
                        "caption": {"type": "string"}, "scene": {"type": "string"}}}
BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "context": {"type": "string"}, "example": {"type": "string"}, "takeaway": {"type": "string"},
        "pattern": {"type": "string", "enum": list(briefmod.PATTERNS)}, "question": {"type": "string"},
        "systems": {"type": "array", "items": _SYSTEM, "maxItems": 8},
        "flow": {"type": "array", "items": _STEP, "maxItems": 12},
    },
    "required": ["context", "example", "takeaway", "pattern", "question", "systems", "flow"],
    "additionalProperties": False,
}


class TopicAgent(Agent):
    id = "topic"
    title = "Topic Scout"
    name = "Nova"
    role = "Picks today's topic from the schedule, avoiding anything already posted."

    def run(self, ctx, guidance):
        planned = None if guidance else planned_for(ctx.ws, ctx.day, ctx.category, ctx.platform)
        if planned:  # the Week Planner or the owner already chose this day's topic
            return self._planned(ctx, planned)
        if ctx.cat["media"] == "animation":
            return self._algorithm(ctx)
        if ctx.category == "week-recap":
            return self._recap(ctx)
        system = self.prompt(ctx, category=ctx.cat["label"], brief=ctx.cat["brief"],
                             research=ctx.cat.get("research", "optional"))
        age = ctx.cat.get("max_source_age_days")
        prompt = (f"Post date: {ctx.day.isoformat()} ({ctx.day.strftime('%A')})\n"
                  + (f"Freshness: the story's primary source must be published between "
                     f"{(ctx.day - timedelta(days=age)).isoformat()} and {ctx.day.isoformat()}. Older news is "
                     f"rejected.\n" if age else "")
                  + f"Category: {ctx.category} - {ctx.cat['label']}\n"
                  f"What this category is: {ctx.cat['brief']}\n"
                  + (briefmod.cat_context(ctx.cat) + "\n" if briefmod.cat_context(ctx.cat) else "") + "\n"
                  f"Recent posts (do NOT repeat these topics or angles):\n{recent_block(ctx)}"
                  + guidance_block(guidance))
        tools = ["WebSearch"] if ctx.cat.get("research") == "required" else []
        return self.ask(ctx, system, prompt, SCHEMA, tools)

    def _planned(self, ctx, e):
        out = {"topic": e["topic"], "angle": e.get("angle") or e["topic"], "why_now": "from the week plan",
               "search_queries": e.get("search_queries", []), "planned": e.get("source", "planner")}
        if e.get("algo") in tracers.TRACERS:
            return dict(out, algo=e["algo"])
        brief = self._brief(ctx, e, out)
        if brief:
            out["brief"] = brief
        if ctx.category == "week-recap":
            return dict(self._recap(ctx), planned="auto")
        if ctx.cat["media"] == "animation":
            return self._algorithm(ctx)
        if ctx.cat.get("research") != "off" and not out["search_queries"]:
            # a topic typed by hand has no search queries yet: ask for them, keep the topic
            system = self.prompt(ctx, category=ctx.cat["label"], brief=ctx.cat["brief"],
                                 research=ctx.cat.get("research", "optional"))
            got = self.ask(ctx, system, f"THE TOPIC IS ALREADY CHOSEN by the owner. Keep it exactly.\n"
                                        f"Topic: {e['topic']}\nAngle: {out['angle']}\nPost date: {ctx.day.isoformat()}\n"
                                        f"Give why_now and the search_queries for this topic.", SCHEMA,
                           ["WebSearch"] if ctx.cat.get("research") == "required" else [])
            out.update(why_now=got.get("why_now", out["why_now"]), search_queries=got.get("search_queries", []))
        return out

    def _brief(self, ctx, e, out):
        """The owner's brief for this day (checked), completed by AI when the category says briefing=auto."""
        mode = briefmod.briefing_mode(ctx.cat)
        if mode == "off" or not e.get("brief") or ctx.cat["media"] == "animation" or ctx.category == "week-recap":
            return {}
        try:
            brief = briefmod.normalize(e["brief"])
        except briefmod.BriefError as err:
            ctx.run.event(self.id, "brief", f"the brief for this day was ignored: {err}", level="warning")
            return {}
        gaps = briefmod.missing(brief, ctx.cat) if mode == "auto" else []
        if gaps:
            try:
                got = self.ask(ctx, self.prompt(ctx, "brief", category=ctx.cat["label"]),
                               f"Topic: {out['topic']}\nAngle: {out['angle']}\nFill in ONLY these fields: {', '.join(gaps)}.\n"
                               f"What the owner already wrote (keep consistent with it):\n"
                               f"{briefmod.to_text(brief)}", BRIEF_SCHEMA)
                brief = briefmod.merge_generated(brief, got, gaps)
                ctx.run.event(self.id, "brief", f"filled in: {', '.join(brief.get('generated', []))}")
            except (AgentError, briefmod.BriefError) as err:
                if getattr(err, "fatal", False):
                    raise
                ctx.run.event(self.id, "brief", f"could not complete the brief, using it as written: {err}",
                              level="warning")
        return brief

    def _algorithm(self, ctx):
        texts = [f"{p.get('topic', '')} {p.get('text', '')}" for p in ctx.recent(200)]
        algo = tracers.next_algo(texts)
        if not algo:
            raise AgentError("every algorithm in the library has been posted; add one to postcrew/render/tracers.py",
                             fatal=True)
        return {"topic": f"{algo.title} in Java", "angle": algo.subtitle, "why_now": "next algorithm in the series",
                "search_queries": [], "algo": algo.id}

    def _recap(self, ctx):
        since = (ctx.day - timedelta(days=7)).isoformat()
        week = [p for p in ctx.ws.history() if (p.get("platform") or "linkedin") == ctx.platform and since <= p.get("date", "") < ctx.day.isoformat()]
        if not week:
            raise AgentError("nothing was published in the last 7 days, so there is no week to recap", fatal=True)
        return {"topic": f"Week in review {ctx.day.isoformat()}", "angle": "the three most useful takeaways",
                "why_now": "weekly recap", "search_queries": [],
                "week_posts": [{"date": p["date"], "topic": p.get("topic", ""), "text": p.get("text", "")} for p in week]}

    def validate(self, ctx, out):
        problems = []
        topic = (out.get("topic") or "").strip()
        if not 5 <= len(topic) <= 90:
            problems.append(f"topic must be 5-90 characters (got {len(topic)})")
        if not (out.get("angle") or "").strip():
            problems.append("angle is empty: say what the reader will learn or be able to do")
        if ctx.category != "week-recap" and out.get("planned") != "manual":  # the owner's own choice stands
            dup = repeat_problem(topic, "", ctx.recent(60))
            if dup:
                problems.append(dup + "; pick a different topic")
        if ctx.cat.get("research") == "required" and not out.get("search_queries"):
            problems.append("this category needs research: give 1-5 search queries")
        return problems

    def summary(self, out):
        return out.get("topic", "")
