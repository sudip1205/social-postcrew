"""Week Planner: drafts the topic for every remaining day of the current week (Monday-Sunday), so you can review,
edit or swap any of them before the crew writes the post. The plan lives in state/plan.json; the Topic Scout uses a day's planned
topic instead of picking one itself.

Each plan entry: {"category", "topic", "angle", "search_queries", "source": planner|manual|auto, "rejected": [...]}.
Your topic ideas (Settings > Topic ideas: a list per category, plus a focus for the whole plan) come first: the
planner uses an unused idea before inventing one. Categories with "plan_ahead": false (fresh news) are left to the Topic Scout the day before, unless you set a
topic for that day yourself or ask the planner for one.
"""
import re
import threading
from datetime import date, datetime, timedelta, timezone

from ..checks import repeat_problem
from ..render import tracers
from ..runlog import RunLog
from ..workspace import WEEKDAYS
from .base import Agent, AgentError, RunContext, guidance_block, recent_block

_lock = threading.Lock()

SCHEMA = {
    "type": "object",
    "properties": {"days": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD, one of the requested dates"},
            "topic": {"type": "string", "description": "Short topic name, 5-90 chars"},
            "angle": {"type": "string", "description": "What the reader will learn or be able to do"},
            "search_queries": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        },
        "required": ["date", "topic", "angle", "search_queries"], "additionalProperties": False}}},
    "required": ["days"],
    "additionalProperties": False,
}


# ---------- the plan file ----------
def load_plan(ws):
    return ws.state("plan", {"days": {}})["days"]


def set_entry(ws, day, entry):
    """entry None removes the day (the Topic Scout then picks the topic the day before)."""
    with _lock:
        data = ws.state("plan", {"days": {}})
        if entry is None:
            data["days"].pop(day, None)
        else:
            data["days"][day] = dict(entry, updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        ws.save_state("plan", data)


def planned_for(ws, day, category):
    e = load_plan(ws).get(day.isoformat() if hasattr(day, "isoformat") else day)
    return e if e and e.get("category") == category and e.get("topic") else None


def this_week(today):
    """Monday-Sunday of the week `today` is in."""
    start = today - timedelta(days=today.weekday())
    return [start + timedelta(days=i) for i in range(7)]


def days_left(today):
    """The days still to plan this week: tomorrow to Sunday (today's post is already being written)."""
    return [d for d in this_week(today) if d > today]


def idea_status(ws, cfg=None):
    """{category: [{"idea", "used_on"}]}: used_on = date of the published or planned post that covers the idea."""
    cfg = cfg or ws.config()
    plan = load_plan(ws)
    covered = [{"topic": p.get("topic", ""), "date": p.get("date", "")} for p in ws.recent_posts(200)]
    covered += [{"topic": e.get("topic", ""), "date": d} for d, e in plan.items() if e.get("topic")]
    out = {}
    for cid, c in cfg["categories"].items():
        rows = []
        for idea in c.get("ideas", []):
            hit = next((h for h in covered if idea_matches(idea, h["topic"])), None)
            rows.append({"idea": idea, "used_on": hit["date"] if hit else None})
        out[cid] = rows
    return out


def idea_matches(idea, topic):
    words = lambda s: {w for w in re.findall(r"[a-z0-9+#]+", s.lower()) if len(w) > 2 and w not in STOP}
    a, b = words(idea), words(topic)
    return bool(a) and (repeat_problem(idea, "", [{"topic": topic}]) is not None or len(a & b) >= max(1, (len(a) + 1) // 2))


STOP = {"the", "and", "for", "with", "how", "why", "what", "you", "your", "into", "from", "explained", "about", "using"}


def taken_dates(ws):
    """Dates already written (queued) or published by Postcrew: their topic can no longer be planned.
    Imported posts only count for repeats; their dates came from another tool."""
    return ({p["date"] for p in ws.queue() if p.get("status") not in ("vetoed", "failed")}
            | {p.get("date") for p in ws.history() if not p.get("imported")})


class PlannerAgent(Agent):
    id = "planner"
    title = "Week Planner"
    name = "Vega"
    role = "Drafts the topic for every remaining day of this week; you can edit any day or ask for another topic."

    def plan(self, ws, days, llm=None, hint="", force=False, replan=False):
        """Plan `days` (dates). force=True also plans fresh-news days and replaces existing entries, rejecting
        the old topic ('Suggest another'). replan=True replaces the planner's own entries without rejecting them
        (after you change your ideas); topics you typed yourself are kept. Returns {date: entry or {"error"}}."""
        from ..llm import make_backend
        cfg = ws.config()
        plan, taken = load_plan(ws), taken_dates(ws)
        todo = []
        for d in days:
            iso, cat = d.isoformat(), cfg["schedule"]["days"].get(WEEKDAYS[d.weekday()])
            if not cat or cat not in cfg["categories"] or iso in taken:
                continue
            e, ahead = plan.get(iso), cfg["categories"][cat].get("plan_ahead", True)
            if replan:
                if (e and e.get("source") in ("manual", "auto")) or (not e and not ahead):
                    continue
            elif not force and (e or not ahead):
                continue
            todo.append((d, cat))
        if not todo:
            return {}
        run_id = datetime.now().strftime("plan-%Y%m%d-%H%M%S")
        run = RunLog(ws.root / "plans" / run_id, run_id, meta={"dates": [d.isoformat() for d, _ in todo]})
        ctx = RunContext(ws=ws, cfg=cfg, day=todo[0][0], category=todo[0][1], run=run, llm=llm or make_backend(cfg, ws.secrets()))
        run.event("planner", "started", f"planning {len(todo)} day(s): {', '.join(d.isoformat() for d, _ in todo)}")
        out = {}
        for d, cat in [x for x in todo if cfg["categories"][x[1]]["media"] == "animation" or x[1] == "week-recap"]:
            out[d.isoformat()] = self._fixed(ctx, d, cat, plan, out)
        llm_days = [x for x in todo if d_iso(x) not in out]
        if llm_days:
            focus = cfg["planning"].get("focus", "").strip()
            out.update(self._ask_days(ctx, llm_days, plan, "\n".join(h for h in (focus, hint) if h), replan))
        for iso, e in out.items():
            if "error" not in e:
                old = plan.get(iso) or {}
                rejected = (old.get("rejected", []) + ([old["topic"]] if force and not replan and old.get("topic")
                                                       else []))[-10:]
                set_entry(ws, iso, dict(e, rejected=rejected))
        ok = sum(1 for e in out.values() if "error" not in e)
        run.finish("succeeded" if ok == len(out) else "failed", f"planned {ok} of {len(out)} day(s)")
        return out

    def _fixed(self, ctx, d, cat, plan, out):
        """Algorithm days take the next unposted algorithm; recap days need no topic."""
        if cat == "week-recap":
            return {"category": cat, "topic": f"Week in review {d.isoformat()}", "angle": "the week's best takeaways",
                    "search_queries": [], "source": "auto"}
        old = plan.get(d.isoformat()) or {}
        texts = ([f"{p.get('topic', '')} {p.get('text', '')}" for p in ctx.recent(200)]
                 + [e.get("topic", "") for k, e in {**plan, **out}.items() if k != d.isoformat()]
                 + [old.get("topic", "")] + old.get("rejected", []))
        algo = tracers.next_algo([t for t in texts if t])
        if not algo:
            return {"error": "every algorithm in the library is posted or planned"}
        return {"category": cat, "topic": f"{algo.title} in Java", "angle": algo.subtitle, "search_queries": [],
                "algo": algo.id, "source": "auto"}

    def _ask_days(self, ctx, todo, plan, hint, replan=False):
        cfg, pl = ctx.cfg, ctx.cfg["pipeline"]
        others = {k: e for k, e in plan.items() if k not in {d_iso(x) for x in todo} and e.get("topic")}
        covered = [p.get("topic", "") for p in ctx.recent(200)] + [e["topic"] for e in others.values()]
        blocks = {}
        for d, cat in todo:
            c, old = cfg["categories"][cat], plan.get(d.isoformat()) or {}
            avoid = [t for t in old.get("rejected", []) + ([] if replan else [old.get("topic", "")]) if t]
            ideas = [i for i in c.get("ideas", []) if not any(idea_matches(i, t) for t in covered + avoid)]
            blocks[d.isoformat()] = (f"DATE {d.isoformat()} ({d.strftime('%A')}) - category {cat}: {c['label']}\n"
                                     f"What it needs: {c['brief']}\nResearch: {c.get('research', 'optional')}"
                                     + (f"\nTHE OWNER'S TOPIC IDEAS for this category, not used yet: {ideas}. Base this "
                                        f"day on one of them (the earliest that fits); use each idea once across the plan."
                                        if ideas else "")
                                     + (f"\nThe owner rejected these, do NOT propose them again: {avoid}" if avoid else ""))
        system = self.prompt(ctx)
        tools = ["WebSearch"] if any(cfg["categories"][c].get("research") == "required" for _, c in todo) else []
        result, guidance = {}, []
        for attempt in range(1, pl["max_attempts_per_step"] + 1):
            left = [x for x in todo if d_iso(x) not in result]
            prompt = (f"Plan these {len(left)} day(s):\n\n" + "\n\n".join(blocks[d_iso(x)] for x in left)
                      + f"\n\nAlready published (never repeat a topic or angle):\n{recent_block(ctx, 60)}"
                      + ("\n\nAlready planned for other days (do not duplicate):\n" +
                         "\n".join(f"- {k} {e['topic']}" for k, e in sorted(others.items())) if others else "")
                      + (f"\n\nWHAT THE OWNER ASKED FOR: {hint}" if hint else "") + guidance_block(guidance))
            try:
                data = self.ask(ctx, system, prompt, SCHEMA, tools)
            except AgentError as e:
                ctx.run.event("planner", "error", str(e), level="error")
                guidance = [f"{d_iso(x)}: {e}" for x in left]
                if e.fatal:
                    break
                continue
            guidance = []
            by_date = {x["date"]: x for x in data.get("days", [])}
            chosen = [e["topic"] for e in others.values()] + [e["topic"] for e in result.values()]
            for d, cat in left:
                x, iso = by_date.get(d.isoformat()), d.isoformat()
                problems = self.problems(ctx, x, cat, chosen, plan.get(iso))
                if problems:
                    guidance += [f"{iso}: {p}" for p in problems]
                    continue
                result[iso] = {"category": cat, "topic": x["topic"].strip(), "angle": x["angle"].strip(),
                               "search_queries": x.get("search_queries", []), "source": "planner"}
                chosen.append(x["topic"])
            ctx.run.event("planner", "validated", f"attempt {attempt}: {len(result)} of {len(todo)} day(s) accepted",
                          {"problems": guidance}, level="warning" if guidance else "info")
            if len(result) == len(todo):
                break
        for x in todo:
            result.setdefault(d_iso(x), {"error": "; ".join(g[len(d_iso(x)) + 2:] for g in guidance
                                                    if g.startswith(d_iso(x)))[:300]
                                         or "the planner could not find a topic"})
        return result

    def problems(self, ctx, x, cat, chosen, old):
        if not x:
            return ["no topic was given for this date"]
        topic = (x.get("topic") or "").strip()
        out = []
        if not 5 <= len(topic) <= 90:
            out.append(f"topic must be 5-90 characters (got {len(topic)})")
        if not (x.get("angle") or "").strip():
            out.append("angle is empty")
        dup = repeat_problem(topic, "", ctx.recent(60)) or repeat_problem(topic, "", [{"topic": t} for t in chosen])
        if dup:
            out.append(dup + "; pick a different topic")
        if old and repeat_problem(topic, "", [{"topic": t} for t in old.get("rejected", []) + [old.get("topic", "")]]):
            out.append(f"'{topic}' was rejected by the owner; propose something different")
        if ctx.cfg["categories"][cat].get("research") == "required" and not x.get("search_queries"):
            out.append("this category needs research: give 1-5 search queries")
        return out


def d_iso(item):
    return item[0].isoformat()


def plan_week(ws, today, llm=None):
    """The scheduler's weekly job: plan the open days left in the current week."""
    out = PlannerAgent().plan(ws, days_left(today), llm=llm)
    if not out:
        return out
    bad = {k: e["error"] for k, e in out.items() if "error" in e}
    from ..notify import notify
    cats = ws.config()["categories"]
    rows = [(date.fromisoformat(d).strftime("%a %d %b"), f"could not plan: {e['error']}" if "error" in e else
             f"{e['topic']}  ({cats.get(e.get('category'), {}).get('label', e.get('category', ''))})")
            for d, e in sorted(out.items())]
    notify(ws, "This week's topics are ready" if not bad else "Some topics could not be planned",
           f"{len(out) - len(bad)} day(s) planned" + (f"; {len(bad)} failed: {next(iter(bad.values()))}" if bad else "")
           + ". Review or change them in the Plan tab.", level="warning" if bad else "info",
           action={"label": "Open the plan", "tab": "plan"}, details={"rows": rows})
    return out
