"""The demo provider: a full, real crew run on scripted answers, with no network and no AI."""
import unittest
from datetime import date, timedelta
from unittest import mock

from helpers import TempWorkspace
from postcrew import demo
from postcrew.agents.planner import plan_week
from postcrew.crew import run_crew
from postcrew.workspace import validate_config


def demo_ws(ws):
    cfg = ws.config()
    cfg["llm"]["backend"] = "demo"
    cfg["team"].update(research=2, writer=2, pre_review=True)   # the demo uses the default team
    ws.save_config(cfg)
    return ws


@mock.patch.object(demo.Demo, "pause_s", 0)
class DemoTests(unittest.TestCase):
    def test_a_full_run_passes_every_check_after_one_send_back(self):
        with TempWorkspace() as ws:
            demo_ws(ws)
            self.assertEqual(validate_config(ws.config()), [])
            with mock.patch("postcrew.checks.fetch_text", side_effect=AssertionError("went online")):
                res = run_crew(ws, date.today() + timedelta(days=1), demo.CATEGORY)
            self.assertTrue(res["ok"], res)
            post = ws.queue()[0]
            self.assertTrue(post["text"].startswith(demo.HOOK_2))   # the Editor's fix was applied
            self.assertTrue(ws.config()["publishing"]["dry_run"])
            events = (ws.runs_dir / res["run_id"] / "events.jsonl").read_text()
            self.assertIn("Editor scored 76", events)

    def test_other_categories_are_refused_with_a_clear_reason(self):
        with TempWorkspace() as ws:
            demo_ws(ws)
            res = run_crew(ws, date.today() + timedelta(days=1), "dev-tip")
            self.assertFalse(res["ok"])
            self.assertIn("demo only writes", res["reason"])

    def test_the_week_planner_answers_too(self):
        with TempWorkspace() as ws:
            demo_ws(ws)
            plan = plan_week(ws, date.today())
            self.assertTrue(plan)
            self.assertTrue(all(e.get("topic") for e in plan.values()), plan)


if __name__ == "__main__":
    unittest.main()
