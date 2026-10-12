"""Start a crew run for one post date."""
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .agents.base import RunContext
from .agents.supervisor import Supervisor
from .checks import fetch_text
from .llm import make_backend
from .runlog import RunLog
from .workspace import WEEKDAYS

_running = threading.Lock()


def local_now(cfg):
    return datetime.now(ZoneInfo(cfg["schedule"]["timezone"]))


def category_for(cfg, day):
    return cfg["schedule"]["days"].get(WEEKDAYS[day.weekday()]) or None


def target_date(cfg, now=None):
    return (now or local_now(cfg)).date() + timedelta(days=cfg["schedule"]["lead_days"])


def run_crew(ws, day=None, category=None, llm=None, fetch=fetch_text, dry_run=False, echo=False, run_id=None):
    """Run the whole crew for one post. Returns the supervisor result plus run_id. One run at a time."""
    cfg = ws.config()
    day = day or target_date(cfg)
    if isinstance(day, str):
        day = date.fromisoformat(day)
    category = category or category_for(cfg, day)
    if not category:
        return {"ok": False, "reason": f"no category is scheduled for {day.strftime('%A')}", "run_id": None}
    if category not in cfg["categories"]:
        return {"ok": False, "reason": f"unknown category {category!r}", "run_id": None}
    if not _running.acquire(blocking=False):
        return {"ok": False, "reason": "another crew run is in progress", "run_id": None}
    try:
        run_id = run_id or ws.new_run_id(day.isoformat())
        run = RunLog(ws.runs_dir / run_id, run_id, meta={"date": day.isoformat(), "category": category,
                                                         "label": cfg["categories"][category]["label"],
                                                         "dry_run": dry_run}, echo=echo)
        ctx = RunContext(ws=ws, cfg=cfg, day=day, category=category, run=run, llm=llm or make_backend(cfg),
                         fetch=fetch, dry_run=dry_run)
        if dry_run:  # rehearse every agent, but never touch the queue
            from .agents.supervisor import CREW
            crew = [a for a in CREW if a.id != "publisher"]
            run.step("publisher", "skipped", summary="dry run: not queued")
            result = Supervisor(crew).run(ctx)
        else:
            result = Supervisor().run(ctx)
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
                                          "meta", "interventions")})
    return sorted(out, key=lambda r: r.get("started_at") or "", reverse=True)[:limit]  # newest run first
