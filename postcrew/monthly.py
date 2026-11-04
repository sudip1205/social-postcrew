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
import copy
import random
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from . import brief as briefmod
from . import platforms
from .agents.base import Agent, AgentError, RunContext, guidance_block
from .agents.planner import load_plan, set_entry
from .checks import norm, repeat_problem
from .platforms import LINKEDIN
from .runlog import RunLog

PER_TOPIC = 10        # kept for callers that ask how many plans one topic gets (LinkedIn now plans a month's days across its topics)
PER_TOPIC_YT = 6      # YouTube: 5-6 trend-researched plans per topic; more than the days, because plans can also be run by hand
MIN_PER_TOPIC_YT = 5
FORMATS = ("short", "long")
MAX_PER_DAY = 5   # plans waiting on one day
_lock = threading.Lock()
_generating = {}   # one generation at a time per app: the scheduler and the Generate plan button must not both write the same plans

SCHEMA = {
    "type": "object",
    "properties": {"plans": {"type": "array", "maxItems": 12, "items": {
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


# interview coaching, career advice, roadmaps, tips and concept lists are not what the YouTube channel makes (hands-on builds and solved problems are)
NOT_NICHE = re.compile(r"(how to|ways? to|steps? to|tips?|framework|strategy|guide)\b[^.?!]{0,40}\b(answer|ace|crack|pass|nail|prepare|prep|survive)\b[^.?!]{0,30}\binterview"
                       r"|\bwhat (the )?interviewers?\b|\binterview (tips|framework|strategy|prep|preparation|mistakes|checklist|roadmap)\b|\b(any|every|a) (system design |coding )?interview\b"
                       r"|\bcrack(ing)? the\b[^.?!]{0,20}\binterview|\binterview\b[^.?!]{0,25}\b(how to|tips|prepare|prep)\b|\broadmap\b|\bcareer\b|\b\d+ (concepts|things|tips|mistakes|rules)\b", re.I)

TREND = {
    "type": "object",
    "properties": {
        "why": {"type": "string", "description": "1-2 sentences: why this is a good topic right now, from the videos' numbers"},
        "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                     "description": "ids of the listed videos that show demand for this plan"},
        "covers": {"type": "array", "items": {"type": "string"}, "maxItems": 5, "description": "what those videos cover"},
        "gap": {"type": "string", "description": "what they miss or explain badly: where this plan can be better"},
    },
    "required": ["why", "evidence", "covers", "gap"], "additionalProperties": False,
}


def schema_for(platform):
    """The Planner's answer: YouTube plans also say which trending videos they answer to (and why, what those cover, what they miss)."""
    if platform == LINKEDIN:
        return SCHEMA
    item = dict(SCHEMA["properties"]["plans"]["items"])
    item["properties"] = dict(item["properties"], trend=TREND)
    item["required"] = item["required"] + ["trend"]
    return dict(SCHEMA, properties={"plans": dict(SCHEMA["properties"]["plans"], items=item)})


def per_topic(platform, month, topics):
    """How many plans each topic gets. LinkedIn: a month's days spread over its topics (one post a day is all it needs). YouTube: 5-6 per topic."""
    if platform != LINKEDIN:
        return PER_TOPIC_YT
    first = date.fromisoformat(month + "-01")
    days = (date(first.year + (first.month == 12), first.month % 12 + 1, 1) - first).days
    return max(3, -(-days // max(1, len(topics))))


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
            r = i.get("research") or {}
            days.setdefault(iso, []).append({"id": i["id"], "title": i["title"], "topic": i["topic"], "status": status_of(i, posted),
                                             "format": i["assigned"].get("format"),
                                             "trend": {"label": r.get("label"), "score": r.get("trend_score")} if r.get("trend_score") is not None else None})
    for iso, rows in days.items():
        for n, r in enumerate(rows, 1):
            r["position"], r["of"] = n, len(rows)
    first = date.fromisoformat(month + "-01")
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    meta = pool["months"].get(month) or {}
    count = lambda s: sum(1 for i in items if i["status"] == s)
    return {"platform": platform, "month": month, "items": items, "days": days,
            "topics": topics_of(cfg), "plan_topics": meta.get("topics", []), "generated_at": meta.get("generated_at"),
            "next_plan": nxt.isoformat(), "per_topic": per_topic(platform, month, topics_of(cfg)),
            "counts": {"plans": len(items), "assigned": count("assigned") + count("written"), "unassigned": count("unassigned"),
                       "published": count("published")},
            "max_per_day": MAX_PER_DAY, "formats": platform != LINKEDIN, "default_format": (cfg.get("video") or {}).get("format", "short")}


# ---------- generating ----------
def _research_block(research):
    from . import trends
    m = research.get("metrics") or {}
    return ("\n\nWHAT IS WORKING ON YOUTUBE RIGHT NOW FOR THIS TOPIC (real numbers read from YouTube today; ids are for the 'evidence' field):\n"
            + trends.brief_videos(research["videos"]) + "\n"
            + (f"Overall: median {m.get('median_views', 0):,} views per video, {m.get('views_per_day', 0):,} views per day, "
               f"{m.get('engagement_pct')}% of viewers like, trend {m.get('trend_score')}/100 ({m.get('label')}).\n" if m else ""))


def _plan_research(trend, research, ids):
    """What a plan stores of its research: how trendy it is, how engaging, the videos that show it, what they cover and what they miss."""
    from . import trends
    chosen = [i for i in (trend.get("evidence") or []) if i in ids][:4]
    vids = trends.evidence(research["videos"], chosen)
    full = [v for v in research["videos"] if v["id"] in chosen]
    m = trends.metrics(full) or {}
    niche = research.get("metrics") or {}
    return {"why": str(trend.get("why") or "").strip(), "covers": [str(c).strip() for c in trend.get("covers") or []][:5], "gap": str(trend.get("gap") or "").strip(),
            "videos": vids, "trend_score": m.get("trend_score", niche.get("trend_score")), "label": m.get("label", niche.get("label")),
            "avg_views": m.get("avg_views", niche.get("avg_views")), "avg_likes": m.get("avg_likes", niche.get("avg_likes")),
            "engagement_pct": m.get("engagement_pct", niche.get("engagement_pct")), "views_per_day": m.get("views_per_day", niche.get("views_per_day")),
            "niche": {k: niche.get(k) for k in ("videos", "median_views", "avg_likes", "engagement_pct", "views_per_day", "trend_score", "label")},
            "researched_at": research.get("researched_at")}


class MonthPlanner(Agent):
    id = "planner"
    title = "Planner"
    name = "Vega"
    role = "Writes the plans for each of your topics once a month; you assign them to days."

    def write(self, ctx, topic, need, avoid, hint="", research=None):
        """Up to `need` new plans for one topic: [{title, angle, context, example, takeaway, search_queries}]. For YouTube `research` is the niche
        research (trends.niche_research): each plan then also says which trending videos it answers, and carries their numbers."""
        got, guidance = [], []
        system = self.prompt(ctx, "planner_month")
        tools = ["WebSearch"]
        schema = schema_for(ctx.platform)
        videos = (research or {}).get("videos") or []
        ids = {v["id"] for v in videos}
        for _attempt in range(ctx.cfg["pipeline"]["max_attempts_per_step"] + max(0, -(-need // 8) - 1)):
            left = need - len(got)
            if left <= 0:
                break
            taken = avoid + [g["title"] for g in got]
            prompt = (f"THE OWNER'S TOPIC: {topic}\n\nWrite {min(left, 8)} plan(s) about it."
                      + (_research_block(research) if videos else "")
                      + (f"\n\nWHAT THE OWNER ASKED FOR: {hint}" if hint else "")
                      + ("\n\nAlready planned or published (never repeat these or the same idea in other words):\n"
                         + "\n".join(f"- {t}" for t in taken[-120:]) if taken else "")
                      + guidance_block(guidance))
            try:
                data = self.ask(ctx, system, prompt, schema, tools)
            except AgentError as e:
                ctx.run.event("planner", "error", str(e), level="error")
                guidance = [str(e)]
                if e.fatal:
                    raise
                continue
            guidance = []
            for p in data.get("plans", []):
                problems = self.problems(p, taken + [g["title"] for g in got], youtube=ctx.platform != LINKEDIN)
                if problems:
                    guidance.append(f"'{p.get('title', '?')}': " + "; ".join(problems))
                    continue
                plan = {k: (p[k].strip() if isinstance(p[k], str) else p[k]) for k in SCHEMA["properties"]["plans"]["items"]["required"]}
                if videos:
                    plan["research"] = _plan_research(p.get("trend") or {}, research, ids)
                elif ctx.platform != LINKEDIN:   # YouTube did not answer: the plan says so instead of showing made-up numbers
                    plan["research"] = {"unavailable": True, "why": str((p.get("trend") or {}).get("why") or "").strip()}
                got.append(plan)
                if len(got) >= need:
                    break
            ctx.run.event("planner", "validated", f"{topic}: {len(got)} of {need} plan(s) accepted",
                          {"problems": guidance}, level="warning" if guidance else "info")
        return got

    @staticmethod
    def problems(p, taken, youtube=False):
        title, out = (p.get("title") or "").strip(), []
        if youtube and NOT_NICHE.search(f"{title} {p.get('angle', '')}"):
            out.append("this is advice about interviews, careers or learning paths, or a list of concepts: the channel only makes hands-on videos that "
                       "SOLVE one concrete problem or BUILD one concrete thing. Plan the problem or the build itself")
        if not 5 <= len(title) <= 90:
            out.append(f"the title must be 5-90 characters (got {len(title)})")
        for key in ("angle", "context", "example", "takeaway"):
            if not (p.get(key) or "").strip():
                out.append(f"{key} is empty")
        dup = repeat_problem(title, "", [{"topic": t} for t in taken])
        if dup:
            out.append(dup + "; write a different plan")
        return out


def generate(ws, platform=LINKEDIN, month=None, llm=None, today=None, hint="", progress=None):
    """See _generate. A second call for the same app waits for the first, then finds nothing left to write."""
    with _generating.setdefault((str(ws.root), platform), threading.Lock()):
        return _generate(ws, platform, month, llm, today, hint, progress)


def _generate(ws, platform, month, llm, today, hint, progress=None):
    """Top up the month's pool to PER_TOPIC plans for each of the app's topics. Returns
    {"added": n, "topics": {topic: n or {"error"}}}. Plans already there (assigned, written or published) count, and nothing
    already planned or published is written again."""
    from .llm import make_backend
    cfg = platforms.view(ws.config(), platform)
    month = month or month_key(today or date.today())
    topics = topics_of(cfg)
    if not topics:
        raise ValueError(f"{platforms.label(platform)} has no topics yet: add some in Settings > Topics, then generate the plan")
    prune_stale_topics(ws, platform)   # plans of topics you removed from Settings do not live on
    with _lock:
        pool = load(ws, platform)
        have = pool["months"].setdefault(month, {"generated_at": None, "topics": [], "items": []})
        want = per_topic(platform, month, topics)
        floor = MIN_PER_TOPIC_YT if platform != LINKEDIN else want   # a YouTube topic with 5 plans is complete; 6 is the aim
        todo = [(t, want - sum(1 for i in have["items"] if i["topic"] == t)) for t in topics]
        todo = [(t, n) for t, n in todo if n > 0 and want - n < floor]
        if not todo:
            return {"added": 0, "topics": {}}
        avoid = [i["title"] for i in _all_items(pool)] + [p.get("topic", "") for p in ws.recent_posts(200, platform)]
    run_id = datetime.now().strftime("plan-%Y%m%d-%H%M%S")
    run = RunLog(ws.root / "plans" / run_id, run_id, meta={"month": month, "platform": platform})
    ctx = RunContext(ws=ws, cfg=cfg, day=date.fromisoformat(month + "-01"), category="", run=run,
                     llm=llm or make_backend(cfg, ws.secrets()), platform=platform)
    run.event("planner", "started", f"{len(todo)} topic(s) for {month}: {', '.join(t for t, _ in todo)}")
    planner, result, added = MonthPlanner(), {}, 0
    say = progress or (lambda msg: None)
    for n, (topic, need) in enumerate(todo, 1):
        research = None
        say(f"Topic {n} of {len(todo)}: " + (f"researching '{topic}' on YouTube" if platform != LINKEDIN else f"writing plans for '{topic}'"))
        if platform != LINKEDIN:   # YouTube: first see what is working on YouTube for this subject
            from . import trends
            run.event("planner", "research", f"researching '{topic}' on YouTube")
            research = trends.niche_research(topic, log=lambda m: run.event("planner", "video", m))
            m = research.get("metrics") or {}
            run.event("planner", "researched", (f"{len(research['videos'])} videos read: trend {m.get('trend_score')}/100 ({m.get('label')}), "
                                                f"{m.get('engagement_pct')}% like rate, {m.get('views_per_day', 0):,} views/day") if research["videos"] else research.get("error", "no data"),
                      level="info" if research["videos"] else "warning")
        say(f"Topic {n} of {len(todo)}: writing the plans for '{topic}'")
        try:
            plans = planner.write(ctx, topic, need, [a for a in avoid if a], (cfg["planning"].get("focus") or "").strip(), research=research)
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
    bad = [t for t, r in result.items() if isinstance(r, dict) or (want - dict(todo)[t] + r) < floor]
    run.finish("succeeded" if not bad else "failed", f"{added} plan(s) written for {len(todo)} topic(s)")
    return {"added": added, "topics": result}


# ---------- starting again ----------
def _schedule_of(cfg, platform):
    return cfg["schedule"] if platform == LINKEDIN else cfg["platforms"][platform]["schedule"]


def snapshot(ws, platform):
    """Everything Generate plan is about to change (the pool, the calendar dates and the day plans), so a failed generation can put it back."""
    return {"pool": copy.deepcopy(load(ws, platform)), "dates": copy.deepcopy(_schedule_of(ws.config(), platform).get("dates") or []),
            "plan": copy.deepcopy(load_plan(ws, platform))}


def restore(ws, platform, snap):
    with _lock:
        ws.save_state(_name(platform), snap["pool"])
        cfg = ws.config()
        _schedule_of(cfg, platform)["dates"] = snap["dates"]
        ws.save_config(cfg)
        ws.save_state(platforms.state_name("plan", platform), {"days": snap["plan"]})


def clear_plans(ws, platform=LINKEDIN):
    """Generate plan starts clean: every plan that is not made yet (in any month, on a day or not) is removed, with its calendar day. A plan
    whose post is waiting in the Queue is kept (its day stays), and published plans do not need to be kept: the published history is what
    stops a topic being planned again. Returns {"cleared": n, "kept": n}."""
    with _lock:
        pool, posted = load(ws, platform), posted_titles(ws, platform)
        removed, kept, days = 0, 0, set()
        for month, meta in list(pool["months"].items()):
            keep = []
            for i in meta["items"]:
                if status_of(i, posted) == "written" or (i.get("manual") and status_of(i, posted) != "published"):
                    keep.append(i)   # your own plans are never cleared by Generate plan
                    kept += 1
                    continue
                removed += 1
                if i.get("assigned"):
                    days.add(i["assigned"]["date"])
            if keep:
                meta["items"] = keep
            else:
                del pool["months"][month]
        ws.save_state(_name(platform), pool)
        for iso in sorted(days):   # the day loses its plan and its place in the schedule unless a written plan still holds it
            _sync_day(ws, platform, pool, posted, iso)
    return {"cleared": removed, "kept": kept}


def prune_stale_topics(ws, platform=LINKEDIN):
    """Plans for a topic that is no longer in Settings are removed (with their calendar day), unless their post is already written. Changing the
    topics in Settings therefore changes what is planned, instead of the old topics living on in the calendar. Returns the number removed."""
    try:
        topics = {t.lower() for t in topics_of(platforms.view(ws.config(), platform))}
    except KeyError:   # not an app of this workspace: nothing to prune (the caller reports the unknown app itself)
        return 0
    with _lock:
        pool, posted = load(ws, platform), posted_titles(ws, platform)
        gone, days = 0, set()
        for month, meta in list(pool["months"].items()):
            keep = []
            for i in meta["items"]:
                if i["topic"].lower() in topics or i.get("manual") or status_of(i, posted) in ("written", "published"):
                    keep.append(i)
                    continue
                gone += 1
                if i.get("assigned"):
                    days.add(i["assigned"]["date"])
            if len(keep) != len(meta["items"]):
                meta["items"] = keep
                if not keep:
                    del pool["months"][month]
        if gone:
            ws.save_state(_name(platform), pool)
            for iso in sorted(days):
                _sync_day(ws, platform, pool, posted, iso)
    return gone


def regenerate(ws, platform, month, llm=None, today=None, rng=None, progress=None):
    """What the Generate plan button does: clear the plans not made yet, write the month's plans (YouTube: researched on YouTube first) and put
    them on the month's days at random. If no plan could be written the old ones are put back and a ValueError says why.
    Returns {"added", "topics", "cleared", "kept", "calendar"}."""
    snap = snapshot(ws, platform)
    gone = clear_plans(ws, platform)
    try:
        out = generate(ws, platform, month, llm=llm, today=today, progress=progress)
        bad = [r["error"] for r in out["topics"].values() if isinstance(r, dict)]
        if not out["added"]:
            raise ValueError(f"the Planner could not write the plans: {bad[0] if bad else 'nothing was written'}. Your previous plans were kept")
    except Exception:
        restore(ws, platform, snap)
        raise
    if progress:
        progress("Putting the plans on the month's days")
    out["calendar"] = auto_assign(ws, platform, month, today=today, rng=rng)
    return dict(out, **gone)


# ---------- assigning plans to days ----------
def _item(pool, item_id):
    for month in pool["months"].values():
        for i in month["items"]:
            if i["id"] == item_id:
                return i
    raise ValueError("that plan no longer exists")


BRIEF_SHORT = ("A vertical hands-on Short taught like a calm, caring professor to students: it SOLVES one concrete problem or BUILDS one small thing live. State the "
               "problem or the goal with a real input, build it in a few small steps (code or a diagram that grows, one running example with numbers), RUN it and show the "
               "result, show the common mistake, and end kindly. Whole spoken sentences, never clipped notes, never interview advice.")
BRIEF_LONG = ("A 16:9 hands-on class by a calm, caring professor for students: it SOLVES one concrete problem or BUILDS one concrete thing from start to finish. Begin with the "
              "problem the student has, draw the plan, then build it step by step (code in an editor window with its output, or a growing diagram), explaining what, why and how "
              "for every part, run it and show it working, break it on purpose and fix it, check in with the class, and finish with a short recap. Never interview advice.")


def short_fmt(fmt):
    return fmt == "short"


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
                     "format": fmt, "target_seconds": platforms.SHORT_DEFAULT_S if short else platforms.LONG_DEFAULT_S, "kicker": "SHORT" if short else "EXPLAINED",
                     "brief": (BRIEF_SHORT if short else BRIEF_LONG)}
        ws.save_config(cfg)
    else:   # a category made earlier with a length that is no longer allowed (a Short of 45 seconds)
        c = cats[cid]
        brief = BRIEF_SHORT if short_fmt(fmt) else BRIEF_LONG
        if c.get("brief") != brief:   # a category made by an earlier version: teach the way the owner now wants
            c["brief"] = brief
            ws.save_config(cfg)
        lo, hi = (15, platforms.SHORT_MAX_S) if short_fmt(fmt) else (60, 1800)
        if not lo <= int(c.get("target_seconds") or 0) <= hi:
            c["target_seconds"] = platforms.SHORT_DEFAULT_S if short_fmt(fmt) else platforms.LONG_DEFAULT_S
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
    return sorted(live, key=lambda i: (i["assigned"]["date"], status_of(i, posted) != "written", bool(i["assigned"].get("auto")), i["assigned"].get("seq", 0)))


def _entry(item, cat, fmt, platform):
    brief = {}
    try:
        brief = briefmod.normalize({"context": item["context"], "example": item["example"], "takeaway": item["takeaway"],
                                    "example_kind": "scenario", "generated": ["context", "example", "takeaway"]})
    except briefmod.BriefError:
        pass
    if item.get("manual"):   # your own plan: your words, as written, and how you want it made
        try:
            brief = briefmod.normalize({"context": item.get("context", ""), **({"tone": item["tone"]} if item.get("tone") else {})})
        except briefmod.BriefError:
            brief = {}
    entry = {"category": cat, "topic": item["title"], "angle": item["angle"], "search_queries": item["search_queries"],
             "source": "manual", "plan_id": item["id"], "rejected": []}
    if brief:
        entry["brief"] = brief
    if item.get("how") or item.get("manual"):
        entry["owner_plan"] = {k: item.get(k, "") for k in ("title", "context", "how", "references") if item.get(k)}
        src = item.get("source") or {}
        if src.get("statement"):   # the problem read from the PDFs and images you attached (attachments.py)
            from .attachments import statement_text
            entry["owner_plan"]["statement"] = statement_text(src["statement"])
            entry["owner_plan"]["files"] = [f["name"] for f in src.get("files") or []]
    if platform != LINKEDIN:
        entry["format"] = fmt
        if item.get("research") and not item["research"].get("unavailable"):
            entry["research"] = item["research"]   # the trending videos behind this plan: the Researcher studies them for the script
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
    prune_stale_topics(ws, platform)
    with _lock:
        pool = load(ws, platform)
        dates = sorted({i["assigned"]["date"] for i in _all_items(pool) if i.get("assigned")})
        if not dates:
            return
        posted = posted_titles(ws, platform)
        for iso in dates:
            _sync_day(ws, platform, pool, posted, iso)


def assign(ws, platform, item_id, day, fmt=None, today=None, auto=False):
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
        item["assigned"] = {"date": iso, "seq": int(time.time() * 1000), **({"format": fmt} if platform != LINKEDIN else {}),
                            **({"auto": True} if auto else {})}   # a plan put on a day at random yields to one you chose: yours is made first
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


def auto_assign(ws, platform, month=None, today=None, rng=None):
    """After a month's plans are written: put the plans that are not on a day yet on the days of the month that have no plan and no post, at
    random, taking turns between the topics so every subject gets its share. Days already holding a plan (by hand or before) are left as they are.
    Plans that do not fit stay unassigned: on YouTube there are more plans than days, and the rest are the ones you can run by hand.
    Returns {"assigned": n, "days": [dates]}."""
    from .crew import post_for
    rng, today = rng or random.Random(), today or date.today()
    month = month or month_key(today)
    first = date.fromisoformat(month + "-01")
    last = date(first.year + (first.month == 12), first.month % 12 + 1, 1) - timedelta(days=1)
    pool, posted = load(ws, platform), posted_titles(ws, platform)
    busy = {i["assigned"]["date"] for i in _live_items(pool, posted)}
    free = [d.isoformat() for d in (first + timedelta(n) for n in range((last - first).days + 1))
            if d >= today and d.isoformat() not in busy and not post_for(ws, d, platform)]
    by_topic = {}
    for i in pool["months"].get(month, {}).get("items", []):
        if status_of(i, posted) == "unassigned" and not i.get("manual"):   # your own plans wait for you on Manual run
            by_topic.setdefault(i["topic"], []).append(i)
    for rows in by_topic.values():
        rng.shuffle(rows)
    order, done = list(by_topic), []
    rng.shuffle(order)
    waiting = sum(len(rows) for rows in by_topic.values())
    if waiting < len(free):   # fewer plans than free days: they land on random days across the whole month, not on the first ones
        free = sorted(rng.sample(free, waiting))
    for iso in free:
        order = [t for t in order if by_topic[t]]
        if not order:
            break
        topic = order.pop(0)
        order.append(topic)   # the next day takes the next topic
        item = by_topic[topic].pop()
        try:
            assign(ws, platform, item["id"], iso, today=today, auto=True)
            done.append(iso)
        except ValueError:
            continue
    return {"assigned": len(done), "days": done}


# ---------- your own plans (Manual run > Add your own plan) ----------
MANUAL_TOPIC = "Your own plans"
MANUAL_LIMITS = {"title": 150, "context": 3000, "how": 3000, "takeaway": 400, "tone": 300}


def add_manual(ws, platform, title, details="", how="", fmt=None, takeaway="", tone="", references=(), item_id=None, today=None):
    """A plan you write yourself: the topic, what it should cover and how you want it made. It waits on Manual run (never put on a day
    by itself, never cleared by Generate plan) until you run it. item_id: change one of yours. Returns the plan."""
    title = " ".join(str(title or "").split())
    if len(title) < 4:
        raise ValueError("give the plan a topic (a few words at least)")
    vals = {"title": title, "context": str(details or "").strip(), "how": str(how or "").strip(), "takeaway": str(takeaway or "").strip(),
            "tone": str(tone or "").strip()}
    for k, lim in MANUAL_LIMITS.items():
        if len(vals[k]) > lim:
            raise ValueError(f"{k}: keep it under {lim} characters")
    refs = [str(r).strip() for r in (references or []) if str(r).strip()][:8]
    if any(not re.match(r"https?://\S+$", r) for r in refs):
        raise ValueError("references must be links (https://...)")
    if platform != LINKEDIN and fmt not in (None, "short", "long"):
        raise ValueError("format must be short or long")
    first = re.split(r"(?<=[.!?])\s", vals["context"])[0] if vals["context"] else ""
    with _lock:
        pool = load(ws, platform)
        if item_id:
            item = _item(pool, item_id)
            if not item.get("manual"):
                raise ValueError("only your own plans can be changed here")
        else:
            month = month_key(today or date.today())
            m = pool["months"].setdefault(month, {"generated_at": None, "topics": [], "items": []})
            item = {"id": uuid.uuid4().hex[:8], "topic": MANUAL_TOPIC, "manual": True, "assigned": None,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            m["items"].append(item)
        item.update(vals, angle=(first or title)[:400], example=item.get("example", ""), search_queries=[title], references=refs,
                    **({"format": fmt} if fmt else {}))
        ws.save_state(_name(platform), pool)
    return item


def remove_manual(ws, platform, item_id):
    with _lock:
        pool = load(ws, platform)
        item = _item(pool, item_id)
        if not item.get("manual"):
            raise ValueError("only your own plans can be removed here")
        if item.get("assigned"):
            raise ValueError("this plan is already being made: remove it from its day on the Plan page first")
        for meta in pool["months"].values():
            meta["items"] = [i for i in meta["items"] if i["id"] != item_id]
        ws.save_state(_name(platform), pool)
    import shutil
    from pathlib import Path
    shutil.rmtree(Path(ws.root) / "plans" / platform / item_id, ignore_errors=True)   # its attached files
    return {"removed": item_id}


def unassigned(ws, platform=LINKEDIN):
    """Every plan not on a day and not made yet, in all months, the most promising first: what the Manual run page offers."""
    pool, posted = load(ws, platform), posted_titles(ws, platform)
    rows = [dict(i, status="unassigned", month=m) for m, mm in pool["months"].items() for i in mm["items"] if status_of(i, posted) == "unassigned"]
    return sorted(rows, key=lambda r: (-((r.get("research") or {}).get("trend_score") or 0), r["title"]))


def run_plan(ws, platform, item_id, fmt, today=None):
    """Manual run: make a plan now, as a Short or a Long video (YouTube), whatever day it is on. It is put first on today's date and the crew is
    started for today by the caller; the scheduler and the calendar are not otherwise touched. Returns {"date", "category", "item"}."""
    today = today or date.today()
    item = assign(ws, platform, item_id, today.isoformat(), fmt=fmt, today=today)
    with _lock:   # first in line today, so the crew picks this plan and not another one waiting on the same day
        pool = load(ws, platform)
        posted = posted_titles(ws, platform)
        mine = _item(pool, item_id)
        others = [i for i in _live_items(pool, posted, today.isoformat()) if i["id"] != item_id and status_of(i, posted) != "written"]
        mine["assigned"]["seq"] = min([i["assigned"].get("seq", 0) for i in others] + [mine["assigned"]["seq"]]) - 1
        ws.save_state(_name(platform), pool)
        _sync_day(ws, platform, pool, posted, today.isoformat())
    return {"date": today.isoformat(), "category": category_for_item(ws, platform, fmt), "item": item}


# ---------- the scheduler's job ----------
def plan_month(ws, today, llm=None, platform=LINKEDIN):
    """The scheduler's monthly job: write this month's plans for the app's topics. {} when it has no topics."""
    cfg = platforms.view(ws.config(), platform)
    if not topics_of(cfg):
        return {}
    out = generate(ws, platform, month_key(today), llm=llm, today=today)
    out["calendar"] = auto_assign(ws, platform, month_key(today), today=today)   # the month's days are filled at random
    if out["added"] or any(isinstance(r, dict) for r in out["topics"].values()):
        from .notify import notify
        bad = {t: r["error"] for t, r in out["topics"].items() if isinstance(r, dict)}
        who = "" if platform == LINKEDIN else f"{platforms.label(platform)}: "
        notify(ws, who + ("This month's plan is ready" if not bad else "Some topics could not be planned"),
               f"{out['added']} plan(s) written" + (f"; {len(bad)} topic(s) failed: {next(iter(bad.values()))}" if bad else "")
               + ". Assign them to days in the Plan tab.", level="warning" if bad else "info",
               action={"label": "Open the plan", "tab": "plan"})
    return out
