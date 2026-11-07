"""Missed schedule items: a scheduled date whose run never happened is offered again, and made on request, one at a time."""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from helpers import TempWorkspace  # noqa: E402

from postcrew import scheduler  # noqa: E402


def li(items):
    return [(m["date"], m["category"]) for m in items if m["platform"] == "linkedin"]


class MissedTest(unittest.TestCase):
    def now(self, ws, d, h=12):
        return datetime(2026, 11, d, h, 0, tzinfo=ZoneInfo(ws.config()["schedule"]["timezone"]))

    def test_the_last_week_of_unmade_scheduled_days_is_missed(self):
        with TempWorkspace() as ws:
            got = li(scheduler.missed(ws, self.now(ws, 6)))   # Fri: target is Sat 7th (lead 1), so the 7th is not missed yet
            self.assertEqual([d for d, _ in got], [f"2026-10-{30:02d}", "2026-10-31"] + [f"2026-11-0{d}" for d in range(1, 7)])
            self.assertEqual(dict(got)["2026-11-02"], "algorithm")   # Monday's category

    def test_a_made_post_or_a_skipped_day_is_not_missed(self):
        with TempWorkspace() as ws:
            ws.save_queue([{"id": "p1", "date": "2026-11-05", "status": "queued", "platform": "linkedin", "scheduled_at": "2026-11-05T16:00:00+00:00"}])
            scheduler.dismiss_missed(ws, "linkedin", "2026-11-04")
            dates = [d for d, _ in li(scheduler.missed(ws, self.now(ws, 6)))]
            self.assertNotIn("2026-11-05", dates)
            self.assertNotIn("2026-11-04", dates)
            self.assertIn("2026-11-03", dates)

    def test_run_queues_the_day_and_the_scheduler_makes_it_once(self):
        with TempWorkspace() as ws:
            now = self.now(ws, 6, 3)   # before the day's generate time: the scheduler has nothing of its own to do
            self.assertEqual(scheduler.queue_missed(ws, [{"platform": "linkedin", "date": "2026-11-03"}], now), 1)
            self.assertEqual(scheduler.queue_missed(ws, [{"platform": "linkedin", "date": "2026-11-03"}], now), 0)   # already waiting
            self.assertTrue(next(m for m in scheduler.missed(ws, now) if m["date"] == "2026-11-03" and m["platform"] == "linkedin")["queued"])
            runs = []
            kw = dict(runner=lambda w, day, *a, **k: runs.append(day.isoformat()), publisher=lambda *a, **k: [],
                      checker=lambda *a, **k: None, planner=lambda *a, **k: None, cleaner=lambda *a, **k: None, engager=lambda *a: False)
            self.assertIn("catch up 2026-11-03", scheduler.tick(ws, now, **kw))
            scheduler.tick(ws, now, **kw)
            self.assertEqual(runs, ["2026-11-03"])

    def test_a_config_from_before_the_monthly_plan_keeps_its_weekdays(self):
        with TempWorkspace() as ws:
            import json
            f = ws.root / "config.json"
            raw = json.loads(f.read_text())
            raw.pop("topics", None)
            raw["schedule"]["frequency"] = "weekly"
            f.write_text(json.dumps(raw))
            self.assertEqual(ws.config()["schedule"]["frequency"], "weekly")


if __name__ == "__main__":
    unittest.main()
