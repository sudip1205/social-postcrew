"""Built-in scheduler (runs inside `postcrew serve`): plan the week's topics once a week, generate in the
evening, publish in the morning, check credentials daily. Uses the times in config.json; state survives restarts (state/scheduler.json).

If you prefer cron/systemd, use the CLI instead: `postcrew run`, `postcrew publish`, `postcrew check`.
"""
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from .agents.credentials import run_check
from .agents.planner import plan_week
from .agents.publisher import publish_due
from .crew import category_for, local_now, run_crew, target_date
from .notify import notify
from .workspace import WEEKDAYS

TICK_S = 30
PUBLISH_EVERY_S = 15 * 60


def _passed(now, hhmm):
    hh, mm = map(int, hhmm.split(":"))
    return (now.hour, now.minute) >= (hh, mm)


def tick(ws, now=None, runner=run_crew, publisher=publish_due, checker=run_check, planner=plan_week):
    """One scheduler step. Returns the list of things it did (for logs and tests)."""
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

    pn = cfg["planning"]
    if (pn["enabled"] and WEEKDAYS[now.weekday()] == pn["weekday"] and _passed(now, pn["time"])
            and st.get("planned_on") != today):
        st["planned_on"] = today
        ws.save_state("scheduler", st)
        planner(ws, now.date())
        did.append("plan this week")

    target = target_date(cfg, now)
    if (_passed(now, cfg["schedule"]["generate_time"]) and st.get("generated_for") != target.isoformat()
            and category_for(cfg, target)):
        if not any(p["date"] == target.isoformat() and p["status"] not in ("vetoed", "failed") for p in ws.queue()):
            st["generated_for"] = target.isoformat()
            ws.save_state("scheduler", st)
            runner(ws, target)
            did.append(f"generate {target.isoformat()}")

    last = st.get("published_check")
    utc = now.astimezone(timezone.utc)
    if _passed(now, cfg["schedule"]["post_time"]) and (
            not last or utc - datetime.fromisoformat(last) >= timedelta(seconds=PUBLISH_EVERY_S)):
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
