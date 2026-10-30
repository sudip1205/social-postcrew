"""Built-in scheduler (runs inside `postcrew serve`): write the month's plans on the 1st, generate in the
evening, publish in the morning, check credentials daily. Uses the times in config.json; state survives restarts (state/scheduler.json).

If you prefer cron/systemd, use the CLI instead: `postcrew run`, `postcrew publish`, `postcrew check`.
"""
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .agents.credentials import run_check
from .cleanup import run_cleanup
from .monthly import month_key, plan_month, topics_of
from .agents.publisher import publish_due
from . import platforms
from .crew import category_for, is_running, local_now, post_for, run_crew, target_date
from .notify import notify
from .platforms import LINKEDIN

TICK_S = 30
PUBLISH_EVERY_S = 15 * 60


def _passed(now, hhmm):
    hh, mm = map(int, hhmm.split(":"))
    return (now.hour, now.minute) >= (hh, mm)


def _earliest(sched):
    """The first moment of the day anything can go out on this schedule."""
    return min([sched["post_time"]] + list((sched.get("day_times") or {}).values())
               + [e["time"] for e in sched.get("dates") or [] if e.get("time")])


def _call(fn, ws, arg, platform):
    """LinkedIn keeps the original call shape; other apps are told which one."""
    return fn(ws, arg) if platform == LINKEDIN else fn(ws, arg, platform=platform)


def tick(ws, now=None, runner=run_crew, publisher=publish_due, checker=run_check, planner=plan_month, cleaner=run_cleanup):
    """One scheduler step. Returns the list of things it did (for logs and tests).
    Every enabled app plans, generates and publishes on its own schedule."""
    if ws.paused():
        return ["paused"]
    cfg = ws.config()
    now = now or local_now(cfg)
    st = ws.state("scheduler", {})
    did = []
    today = now.date().isoformat()

    if _passed(now, cfg["schedule"]["credential_check_time"]) and st.get("checked") != today:
        st["checked"] = today
        ws.save_state("scheduler", st)
        checker(ws)
        did.append("credentials")

    cl = cfg.get("cleanup") or {}
    if cl.get("enabled", True) and _passed(now, cl.get("time", "03:30")) and st.get("cleaned_on") != today:   # the daily tidy-up
        st["cleaned_on"] = today
        ws.save_state("scheduler", st)
        cleaner(ws)
        did.append("clean up")

    gates = []
    for pid in platforms.enabled(cfg):
        pcfg = platforms.view(cfg, pid)
        sched, who = pcfg["schedule"], "" if pid == LINKEDIN else f"{pid} "
        pnow = now.astimezone(ZoneInfo(sched["timezone"]))
        name = platforms.state_name("scheduler", pid)
        ps = st if pid == LINKEDIN else ws.state(name, {})
        pn = pcfg["planning"]
        # the monthly plan: written once for each month, on the 1st (or the first tick after it, when the app was off or had no
        # topics yet). Topics changed later in the month are used for the next month's plan.
        month = month_key(pnow.date())
        if (pn["enabled"] and _passed(pnow, pn["time"]) and ps.get("planned_month") != month and topics_of(pcfg)):
            ps["planned_month"] = month
            ws.save_state(name, ps)
            _call(planner, ws, pnow.date(), pid)
            did.append(f"plan {month}{'' if pid == LINKEDIN else ' (' + pid + ')'}")

        target = target_date(pcfg, pnow)
        if (_passed(pnow, sched["generate_time"]) and ps.get("generated_for") != target.isoformat()
                and category_for(pcfg, target)):
            # a post for that date already made (e.g. by a manual run) or a run still going: nothing to generate
            if not post_for(ws, target, pid) and not is_running():
                ps["generated_for"] = target.isoformat()
                ws.save_state(name, ps)
                _call(runner, ws, target, pid)
                did.append(f"generate {who}{target.isoformat()}")
        gates.append((pnow, _earliest(sched)))

    last = st.get("published_check")
    utc = now.astimezone(timezone.utc)
    if any(_passed(pnow, t) for pnow, t in gates) and (
            not last or utc - datetime.fromisoformat(last) >= timedelta(seconds=PUBLISH_EVERY_S)):
        st = ws.state("scheduler", {})   # a platform's step above may have rewritten it
        st["published_check"] = utc.isoformat(timespec="seconds")
        ws.save_state("scheduler", st)
        if publisher(ws):
            did.append("publish")
    return did


class Scheduler(threading.Thread):
    def __init__(self, ws):
        super().__init__(daemon=True, name="postcrew-scheduler")
        self.ws = ws
        self.stop = threading.Event()

    def run(self):
        try:
            run_check(self.ws)
        except Exception:
            traceback.print_exc()
        while not self.stop.is_set():
            try:
                tick(self.ws)
            except Exception as e:
                traceback.print_exc()
                notify(self.ws, "Scheduler error", str(e)[:300], level="error", key="scheduler-error", quiet_hours=6)
            self.stop.wait(TICK_S)
