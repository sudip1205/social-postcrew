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
from . import monthly
from .monthly import month_key, plan_month, topics_of
from .agents.publisher import publish_due
from . import engage, platforms
from .crew import category_for, is_running, local_now, post_for, run_crew, target_date
from .notify import notify
from .platforms import LINKEDIN

TICK_S = 30
PUBLISH_EVERY_S = 15 * 60


def _passed(now, hhmm):
    hh, mm = map(int, hhmm.split(":"))
    return (now.hour, now.minute) >= (hh, mm)


def generate_times(sched):
    """The day's run times: schedule.generate_times (one video each), else the single generate_time."""
    times = [t for t in sched.get("generate_times") or [] if isinstance(t, str) and ":" in t]
    return sorted(times) or [sched["generate_time"]]


def _earliest(sched):
    """The first moment of the day anything can go out on this schedule."""
    return min([sched["post_time"]] + list((sched.get("day_times") or {}).values())
               + [e["time"] for e in sched.get("dates") or [] if e.get("time")])


def _call(fn, ws, arg, platform):
    """LinkedIn keeps the original call shape; other apps are told which one."""
    return fn(ws, arg) if platform == LINKEDIN else fn(ws, arg, platform=platform)


def tick(ws, now=None, runner=run_crew, publisher=publish_due, checker=run_check, planner=plan_month, cleaner=run_cleanup, engager=None):
    """One scheduler step. Returns the list of things it did (for logs and tests).
    Every enabled app plans, generates and publishes on its own schedule."""
    if ws.paused():
        return ["paused"]
    for pid in platforms.enabled(ws.config()):   # a day with several plans works on the first one still to make
        monthly.sync_all(ws, pid)
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
        iso = target.isoformat()
        slots = generate_times(sched)   # one run per time: "10:00" and "17:00" make two videos a day
        made = ps.get("generated_slots") if ps.get("generated_slots", {}).get("date") == iso else {"date": iso, "times": []}
        if ps.get("generated_for") == iso and not made["times"]:   # state from before run times: today's one run is made
            made["times"] = slots[:1]
        due = [t for t in slots if _passed(pnow, t) and t not in made["times"]]
        if due and category_for(pcfg, target) and not is_running():
            # nothing to generate when the day is done: with plans, when none of the day's scheduled plans is left to make (a post made by
            # hand or one of your own plans dated that day does not use up a scheduled run); without plans, when a post for that date is
            # already made (e.g. by a manual run), and then only once a day
            planned = (monthly.load_plan(ws, pid).get(iso) or {}).get("plan_id")
            done = not monthly.scheduled_due(ws, pid, iso) if planned else (bool(post_for(ws, target, pid)) or bool(made["times"]))
            if not done:
                made["times"] = made["times"] + [due[0]]
                ps["generated_slots"], ps["generated_for"] = made, iso
                ws.save_state(name, ps)
                _call(runner, ws, target, pid)
                did.append(f"generate {who}{iso} ({due[0]})")
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
    if LINKEDIN in platforms.enabled(ws.config()) and engage.due(ws, now.astimezone(timezone.utc)):
        if (engager or _engage_in_background)(ws):
            did.append("comments")
    return did


_engaging = threading.Lock()


def _engage_in_background(ws):
    """Read and answer comments without holding up the schedule (the Replier may take a minute). One check at a time."""
    if not _engaging.acquire(blocking=False):
        return False

    def go():
        try:
            engage.check(ws)
        except Exception:
            traceback.print_exc()
        finally:
            _engaging.release()
    threading.Thread(target=go, daemon=True, name="postcrew-comments").start()
    return True


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
