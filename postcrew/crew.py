"""Start a crew run for one post date."""
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .agents.base import RunContext
from .agents.supervisor import Supervisor
from .checks import fetch_text
from .llm import make_backend
from .runlog import RunLog
from . import platforms
from .platforms import LINKEDIN

_running = threading.Lock()


def local_now(cfg):
    return datetime.now(ZoneInfo(cfg["schedule"]["timezone"]))


def category_for(cfg, day):
    """The category the schedule has for `day` (cfg: the platform's own view of the config), or None."""
    return platforms.category_for(cfg["schedule"], day)


def target_date(cfg, now=None):
    return (now or local_now(cfg)).date() + timedelta(days=cfg["schedule"]["lead_days"])


def post_for(ws, day, platform=LINKEDIN):
    """The post already made for this date on this platform (queued, awaiting approval or published), or None."""
    day = day.isoformat() if isinstance(day, date) else day
    mine = lambda p: p.get("date") == day and platforms.platform_of(p) == platform
    return next((p for p in ws.queue() if mine(p) and p.get("status") not in ("vetoed", "failed")),
                None) or next((p for p in ws.history() if mine(p)), None)


def run_crew(ws, day=None, category=None, llm=None, fetch=fetch_text, dry_run=False, echo=False, run_id=None,
             platform=LINKEDIN, options=None):
    """Run the whole crew for one post on one platform. Returns the supervisor result plus run_id. One run at a time.
    options: one-off overrides for this run (a YouTube video's "format" and "target_seconds")."""
    full = ws.config()
    try:
        cfg = platforms.view(full, platform)
    except KeyError:
        return {"ok": False, "reason": f"unknown platform {platform!r}", "run_id": None}
    day = day or target_date(cfg)
    if isinstance(day, str):
        day = date.fromisoformat(day)
    category = category or category_for(cfg, day)
    if not category:
        return {"ok": False, "reason": f"no category is scheduled for {day.strftime('%A')}", "run_id": None}
    if category not in cfg["categories"]:
        return {"ok": False, "reason": f"unknown category {category!r}", "run_id": None}
    if cfg["llm"]["backend"] == "demo":
        from . import demo
        if category != demo.CATEGORY:
            return {"ok": False, "reason": f"the demo only writes {cfg['categories'][demo.CATEGORY]['label']} posts: "
                                           f"pick that category, or choose a real AI provider in Settings",
                    "run_id": None}
        if fetch is fetch_text:
            fetch = demo.fetch   # the demo never goes online
    if not _running.acquire(blocking=False):
        return {"ok": False, "reason": "another crew run is in progress", "run_id": None}
    try:
        run_id = run_id or ws.new_run_id(day.isoformat())
        from .agents.supervisor import crew_for
        crew = crew_for(platform, cfg, category)
        run = RunLog(ws.runs_dir / run_id, run_id, meta={"date": day.isoformat(), "category": category,
                                                         "label": cfg["categories"][category]["label"],
                                                         "platform": platform, "dry_run": dry_run}, echo=echo,
                     steps=[a.id for a in crew])
        ctx = RunContext(ws=ws, cfg=cfg, day=day, category=category, run=run, llm=llm or make_backend(cfg, ws.secrets()),
                         fetch=fetch, dry_run=dry_run, platform=platform, options=options or {})
        if dry_run:  # rehearse every agent, but never touch the queue
            crew = [a for a in crew if a.id != "publisher"]
            run.step("publisher", "skipped", summary="dry run: not queued")
            result = Supervisor(crew).run(ctx)
        else:
            result = Supervisor(crew).run(ctx)
        result["run_id"] = run_id
        return result
    finally:
        _running.release()


def is_running():
    return _running.locked()


def list_runs(ws, limit=50):
    import json
    out = []
    for d in ws.runs_dir.glob("*/status.json"):
        try:
            s = json.loads(d.read_text())
        except ValueError:
            continue
        out.append({k: s.get(k) for k in ("run_id", "state", "started_at", "finished_at", "result", "cost_usd",
                                          "tokens", "meta", "interventions")})
    return sorted(out, key=lambda r: r.get("started_at") or "", reverse=True)[:limit]  # newest run first
