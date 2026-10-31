"""The monthly plan: a pool of plans per app, assigned to days by hand.

Settings > Topics holds one-line topics per app. On the 1st of every month (or when you press Generate plan) the Planner writes
PER_TOPIC related plans for each topic: a title, an angle, the context, a real-world example, a takeaway and the research topics.
They are NOT put on days. In the Plan page you assign any plan to a date (for YouTube also Short or Long); that date then gets a
post from the crew. A plan that was published is kept, marked published, and never planned again.

State (state/pool.json, state/pool-youtube.json): {"months": {"2026-11": {"generated_at", "topics": [...], "items": [...]}}}
An item: {id, topic (the owner's line), title, angle, context, example, takeaway, search_queries, assigned: {date, format}|None}.
Assigning writes the day into the app's schedule (schedule.dates) and its plan entry (agents/planner.py), which is what the crew
and the scheduler already read, so nothing else changes in how a post is made.
"""
import re
import threading
import time
import uuid
from datetime import date, datetime, timezone

from . import brief as briefmod
from . import platforms
from .agents.base import Agent, AgentError, RunContext, guidance_block
from .agents.planner import load_plan, set_entry
from .checks import norm, repeat_problem
from .platforms import LINKEDIN
from .runlog import RunLog

PER_TOPIC = 10
FORMATS = ("short", "long")
MAX_PER_DAY = 5   # plans waiting on one day
_lock = threading.Lock()
_generating = {}   # one generation at a time per app: the scheduler and the Generate plan button must not both write the same plans

SCHEMA = {
    "type": "object",
    "properties": {"plans": {"type": "array", "maxItems": PER_TOPIC + 2, "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "working title, 5-90 characters"},
            "angle": {"type": "string", "description": "what the reader or viewer will learn or be able to do"},
            "context": {"type": "string", "description": "2-4 sentences: why it matters, what people get wrong"},
            "example": {"type": "string", "description": "one concrete generic real-world scenario"},
            "takeaway": {"type": "string", "description": "what the reader can do or decide afterwards"},
            "search_queries": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
        },
        "required": ["title", "angle", "context", "example", "takeaway", "search_queries"],
        "additionalProperties": False}}},
    "required": ["plans"],
    "additionalProperties": False,
}


# ---------- the pool ----------
def _name(platform):
    return platforms.state_name("pool", platform)


def month_key(day):
    day = day if isinstance(day, date) else date.fromisoformat(day)
    return f"{day.year:04d}-{day.month:02d}"


def load(ws, platform=LINKEDIN):
    return ws.state(_name(platform), {"months": {}})


def topics_of(cfg):
    """The owner's topic lines of an app: trimmed, no blanks, no repeats."""
    out, seen = [], set()
    for t in cfg.get("topics") or []:
        t = re.sub(r"\s+", " ", str(t)).strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def _mine(platform):
    return lambda p: platforms.platform_of(p) == platform


def posted_titles(ws, platform=LINKEDIN):
    """What was published or written on this app, by the plan's id (when the post came from a plan) and by normalised topic:
    {"id:<plan id>" | topic: "published" | "written"}. Vetoed and failed posts do not count."""
    mine, out = _mine(platform), {}

    def note(p, state):
        for key in ("id:" + p["plan_id"] if p.get("plan_id") else None, norm(p["topic"]) if p.get("topic") else None):
            if key:
                out[key] = state
    for p in ws.queue():
        if mine(p) and p.get("status") not in ("vetoed", "failed"):
            note(p, "written")
    for p in ws.history():
        if mine(p):
            note(p, "published")
    return out


def status_of(item, posted):
    s = posted.get("id:" + item["id"]) or posted.get(norm(item["title"]))
    if s:
        return s
    return "assigned" if item.get("assigned") else "unassigned"


def _all_items(pool):
    return [i for m in pool["months"].values() for i in m["items"]]


def view(ws, platform=LINKEDIN, month=None, today=None):
    """What the Plan page shows for one month: the plans (with their status), the calendar days and the counts."""
    cfg = platforms.view(ws.config(), platform)
    pool, posted = load(ws, platform), posted_titles(ws, platform)
    month = month or month_key(today or date.today())
    items = []
    for i in pool["months"].get(month, {}).get("items", []):
        items.append(dict(i, status=status_of(i, posted)))
    # the calendar: every plan still to make on each day of this month, in the order they are made. A published plan is no longer on the
    # calendar (it stays struck through in the list). A plan assigned in another month's pool can still sit on a day of this month.
    days = {}
    for i in _live_items(pool, posted):
        iso = i["assigned"]["date"]
        if iso.startswith(month):
            days.setdefault(iso, []).append({"id": i["id"], "title": i["title"], "topic": i["topic"], "status": status_of(i, posted),
                                             "format": i["assigned"].get("format")})
    for iso, rows in days.items():
        for n, r in enumerate(rows, 1):
            r["position"], r["of"] = n, len(rows)
    first = date.fromisoformat(month + "-01")
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    meta = pool["months"].get(month) or {}
    count = lambda s: sum(1 for i in items if i["status"] == s)
    return {"platform": platform, "month": month, "items": items, "days": days,
            "topics": topics_of(cfg), "plan_topics": meta.get("topics", []), "generated_at": meta.get("generated_at"),
            "next_plan": nxt.isoformat(), "per_topic": PER_TOPIC,
            "counts": {"plans": len(items), "assigned": count("assigned") + count("written"), "unassigned": count("unassigned"),
                       "published": count("published")},
            "max_per_day": MAX_PER_DAY, "formats": platform != LINKEDIN, "default_format": (cfg.get("video") or {}).get("format", "short")}


# ---------- generating ----------
class MonthPlanner(Agent):
    id = "planner"
    title = "Planner"
    name = "Vega"
    role = "Writes the plans for each of your topics once a month; you assign them to days."

    def write(self, ctx, topic, need, avoid, hint=""):
        """Up to `need` new plans for one topic: [{title, angle, context, example, takeaway, search_queries}]."""
        got, guidance = [], []
        system = self.prompt(ctx, "planner_month")
        tools = ["WebSearch"]
        for _attempt in range(ctx.cfg["pipeline"]["max_attempts_per_step"]):
            left = need - len(got)
            if left <= 0:
                break
            taken = avoid + [g["title"] for g in got]
            prompt = (f"THE OWNER'S TOPIC: {topic}\n\nWrite {left} plan(s) about it."
                      + (f"\n\nWHAT THE OWNER ASKED FOR: {hint}" if hint else "")
                      + ("\n\nAlready planned or published (never repeat these or the same idea in other words):\n"
                         + "\n".join(f"- {t}" for t in taken[-120:]) if taken else "")
                      + guidance_block(guidance))
            try:
                data = self.ask(ctx, system, prompt, SCHEMA, tools)
            except AgentError as e:
                ctx.run.event("planner", "error", str(e), level="error")
                guidance = [str(e)]
                if e.fatal:
                    raise
                continue
            guidance = []
            for p in data.get("plans", []):
                problems = self.problems(p, taken + [g["title"] for g in got])
                if problems:
                    guidance.append(f"'{p.get('title', '?')}': " + "; ".join(problems))
                    continue
                got.append({k: (p[k].strip() if isinstance(p[k], str) else p[k]) for k in SCHEMA["properties"]["plans"]["items"]["required"]})
                if len(got) >= need:
                    break
            ctx.run.event("planner", "validated", f"{topic}: {len(got)} of {need} plan(s) accepted",
                          {"problems": guidance}, level="warning" if guidance else "info")
        return got

    @staticmethod
    def problems(p, taken):
        title, out = (p.get("title") or "").strip(), []
        if not 5 <= len(title) <= 90:
            out.append(f"the title must be 5-90 characters (got {len(title)})")
        for key in ("angle", "context", "example", "takeaway"):
            if not (p.get(key) or "").strip():
                out.append(f"{key} is empty")
        dup = repeat_problem(title, "", [{"topic": t} for t in taken])
        if dup:
            out.append(dup + "; write a different plan")
        return out


def generate(ws, platform=LINKEDIN, month=None, llm=None, today=None, hint=""):
    """See _generate. A second call for the same app waits for the first, then finds nothing left to write."""
    with _generating.setdefault((str(ws.root), platform), threading.Lock()):
        return _generate(ws, platform, month, llm, today, hint)


def _generate(ws, platform, month, llm, today, hint):
    """Top up the month's pool to PER_TOPIC plans for each of the app's topics. Returns
    {"added": n, "topics": {topic: n or {"error"}}}. Plans already there (assigned, written or published) count, and nothing
    already planned or published is written again."""
    from .llm import make_backend
    cfg = platforms.view(ws.config(), platform)
    month = month or month_key(today or date.today())
    topics = topics_of(cfg)
    if not topics:
        raise ValueError(f"{platforms.label(platform)} has no topics yet: add some in Settings > Topics, then generate the plan")
    with _lock:
        pool = load(ws, platform)
        have = pool["months"].setdefault(month, {"generated_at": None, "topics": [], "items": []})
        todo = [(t, PER_TOPIC - sum(1 for i in have["items"] if i["topic"] == t)) for t in topics]
        todo = [(t, n) for t, n in todo if n > 0]
        if not todo:
            return {"added": 0, "topics": {}}
        avoid = [i["title"] for i in _all_items(pool)] + [p.get("topic", "") for p in ws.recent_posts(200, platform)]
    run_id = datetime.now().strftime("plan-%Y%m%d-%H%M%S")
    run = RunLog(ws.root / "plans" / run_id, run_id, meta={"month": month, "platform": platform})
    ctx = RunContext(ws=ws, cfg=cfg, day=date.fromisoformat(month + "-01"), category="", run=run,
                     llm=llm or make_backend(cfg, ws.secrets()), platform=platform)
    run.event("planner", "started", f"{len(todo)} topic(s) for {month}: {', '.join(t for t, _ in todo)}")
    planner, result, added = MonthPlanner(), {}, 0
    for topic, need in todo:
        try:
            plans = planner.write(ctx, topic, need, [a for a in avoid if a], (cfg["planning"].get("focus") or "").strip())
        except AgentError as e:
            result[topic] = {"error": str(e)[:300]}
            continue
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with _lock:   # re-read: the owner may have assigned something while the Planner worked
            pool = load(ws, platform)
            m = pool["months"].setdefault(month, {"generated_at": None, "topics": [], "items": []})
            for p in plans:
                m["items"].append(dict(p, id=uuid.uuid4().hex[:8], topic=topic, assigned=None, created_at=stamp))
            m["generated_at"], m["topics"] = stamp, topics
            ws.save_state(_name(platform), pool)
        avoid += [p["title"] for p in plans]
        result[topic] = len(plans)
        added += len(plans)
    bad = [t for t, r in result.items() if isinstance(r, dict) or r < dict(todo)[t]]
    run.finish("succeeded" if not bad else "failed", f"{added} plan(s) written for {len(todo)} topic(s)")
    return {"added": added, "topics": result}


# ---------- assigning plans to days ----------
def _item(pool, item_id):
    for month in pool["months"].values():
        for i in month["items"]:
            if i["id"] == item_id:
                return i
    raise ValueError("that plan no longer exists")


def category_for_item(ws, platform, fmt):
    """The topic type the crew writes an assigned plan as: LinkedIn uses the deep-dive type, YouTube a Short or a Long video."""
    cfg = ws.config()
    if platform == LINKEDIN:
        cats = cfg["categories"]
        return "briefed" if "briefed" in cats else next((c for c, v in cats.items() if v.get("media") not in ("animation",) and c != "week-recap"), None)
    cid = f"assigned-{fmt}"
    cats = cfg["platforms"][platform].setdefault("categories", {})
    if cid not in cats:
        short = fmt == "short"
        cats[cid] = {"label": "Short video" if short else "Long video", "media": "video", "research": "optional", "fact_check": False,
                     "format": fmt, "target_seconds": 45 if short else 480, "kicker": "SHORT" if short else "EXPLAINED",
                     "brief": ("A vertical Short on this plan: a hook in the first 3 seconds, the idea in 2-4 steps, one line "
                               "asking the viewer to try it. Short sentences, spoken words." if short else
                               "A 16:9 explainer on this plan: a cold open with the problem, why it matters, the idea built up "
                               "in 3-5 scenes with one concrete example, the common mistake, what to do next.")}
        ws.save_config(cfg)
    return cid


def _set_date(ws, platform, day, category):
    """Put (category) or take (None) a date in the app's schedule. Does nothing (no write) when it is already so."""
    cfg = ws.config()
    sched = cfg["schedule"] if platform == LINKEDIN else cfg["platforms"][platform]["schedule"]
    have = next((e.get("category") for e in sched.get("dates") or [] if isinstance(e, dict) and e.get("date") == day), None)
    if have == category:
        return
    dates = [e for e in sched.get("dates") or [] if not (isinstance(e, dict) and e.get("date") == day)]
    if category:
        dates.append({"date": day, "category": category})
    sched["dates"] = sorted(dates, key=lambda e: e.get("date", ""))
    ws.save_config(cfg)


def _live_items(pool, posted, iso=None):
    """The plans still to make or waiting in the Queue, in the order they are made: the one already written first, then the others in
    the order they were assigned. All days, or just `iso`."""
    live = [i for i in _all_items(pool) if i.get("assigned") and (iso is None or i["assigned"]["date"] == iso)
            and status_of(i, posted) in ("assigned", "written")]
    return sorted(live, key=lambda i: (i["assigned"]["date"], status_of(i, posted) != "written", i["assigned"].get("seq", 0)))


def _entry(item, cat, fmt, platform):
    brief = {}
    try:
        brief = briefmod.normalize({"context": item["context"], "example": item["example"], "takeaway": item["takeaway"],
                                    "example_kind": "scenario", "generated": ["context", "example", "takeaway"]})
    except briefmod.BriefError:
        pass
    entry = {"category": cat, "topic": item["title"], "angle": item["angle"], "search_queries": item["search_queries"],
             "source": "manual", "plan_id": item["id"], "rejected": []}
    if brief:
        entry["brief"] = brief
    if platform != LINKEDIN:
        entry["format"] = fmt
    return entry


def _sync_day(ws, platform, pool, posted, iso):
    """Make a day's schedule and plan say what is made next there: the first plan still to make. After one is published the next one becomes
    that plan; with none left the day is taken out of the schedule. The scheduled run makes ONE post a day (the plan that is current when
    it runs); the others are made by hand, one at a time."""
    live = _live_items(pool, posted, iso)
    entry = load_plan(ws, platform).get(iso)
    if not live:
        if entry and entry.get("plan_id"):
            set_entry(ws, iso, None, platform)
        _set_date(ws, platform, iso, None)
        return
    cur = live[0]
    fmt = cur["assigned"].get("format")
    cat = category_for_item(ws, platform, fmt)
    if not entry or entry.get("plan_id") != cur["id"] or entry.get("category") != cat:
        set_entry(ws, iso, _entry(cur, cat, fmt, platform), platform)
    _set_date(ws, platform, iso, cat)


def sync_all(ws, platform=LINKEDIN):
    """Bring every day that has assigned plans up to date (cheap; run before each scheduled and each manual run, and when the page opens)."""
    with _lock:
        pool = load(ws, platform)
        dates = sorted({i["assigned"]["date"] for i in _all_items(pool) if i.get("assigned")})
        if not dates:
            return
        posted = posted_titles(ws, platform)
        for iso in dates:
            _sync_day(ws, platform, pool, posted, iso)


def assign(ws, platform, item_id, day, fmt=None, today=None):
    """Put a plan on a date; a date can hold several, made one at a time. For YouTube `fmt` is "short" or "long". Moves the plan if it
    was on another date. A plan is on one date only."""
    day = date.fromisoformat(day)
    if day < (today or date.today()):
        raise ValueError("that date has passed: pick today or a later day")
    iso = day.isoformat()
    cfg = platforms.view(ws.config(), platform)
    if platform != LINKEDIN:
        fmt = fmt or (cfg.get("video") or {}).get("format", "short")
        if fmt not in FORMATS:
            raise ValueError("pick Short or Long")
    with _lock:
        pool = load(ws, platform)
        item = _item(pool, item_id)
        posted = posted_titles(ws, platform)
        if status_of(item, posted) in ("published", "written"):
            raise ValueError("this plan was already written or published: it is never planned again")
        waiting = [i for i in _live_items(pool, posted, iso) if i["id"] != item_id]
        if len(waiting) >= MAX_PER_DAY:
            raise ValueError(f"{iso} already has {MAX_PER_DAY} plans waiting: make or unassign one first")
        if not category_for_item(ws, platform, fmt):
            raise ValueError("no post type is available for this app")
        old = (item.get("assigned") or {}).get("date")
        item["assigned"] = {"date": iso, "seq": int(time.time() * 1000), **({"format": fmt} if platform != LINKEDIN else {})}
        ws.save_state(_name(platform), pool)
        if old and old != iso:
            _sync_day(ws, platform, pool, posted, old)
        _sync_day(ws, platform, pool, posted, iso)
    return item


def unassign(ws, platform, item_id):
    with _lock:
        pool = load(ws, platform)
        item = _item(pool, item_id)
        a = item.get("assigned")
        if not a:
            return item
        posted = posted_titles(ws, platform)
        if status_of(item, posted) == "written":
            raise ValueError("this plan is already written: veto or delete its post in the Queue first")
        item["assigned"] = None
        ws.save_state(_name(platform), pool)
        _sync_day(ws, platform, pool, posted, a["date"])
    return item


# ---------- the scheduler's job ----------
def plan_month(ws, today, llm=None, platform=LINKEDIN):
    """The scheduler's monthly job: write this month's plans for the app's topics. {} when it has no topics."""
    cfg = platforms.view(ws.config(), platform)
    if not topics_of(cfg):
        return {}
    out = generate(ws, platform, month_key(today), llm=llm, today=today)
    if out["added"] or any(isinstance(r, dict) for r in out["topics"].values()):
        from .notify import notify
        bad = {t: r["error"] for t, r in out["topics"].items() if isinstance(r, dict)}
        who = "" if platform == LINKEDIN else f"{platforms.label(platform)}: "
        notify(ws, who + ("This month's plan is ready" if not bad else "Some topics could not be planned"),
               f"{out['added']} plan(s) written" + (f"; {len(bad)} topic(s) failed: {next(iter(bad.values()))}" if bad else "")
               + ". Assign them to days in the Plan tab.", level="warning" if bad else "info",
               action={"label": "Open the plan", "tab": "plan"})
    return out
