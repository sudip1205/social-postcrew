"""Factory plans (owner, 2026-11-17): topic -> researched plans -> script with your instructions -> your voice -> Make the video, all by hand."""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from helpers import ScriptedLLM, TempWorkspace  # noqa: E402
from test_monthly import answer  # noqa: E402
from test_shorts import fake_factory  # noqa: E402

from postcrew import factory_plans, voice_desk  # noqa: E402

NO_RESEARCH = lambda topic, log=None: {"videos": [], "error": "offline"}   # noqa: E731


def wait(key):
    for _ in range(400):
        j = factory_plans._jobs.get(key)
        if j and j.get("done"):
            return j
        time.sleep(0.02)
    raise AssertionError("the job did not finish")


@mock.patch("postcrew.agents.credentials.check_claude", new=lambda *a, **k: {"state": "ok", "message": "Claude Code is ready"})
class FactoryPlanTests(unittest.TestCase):
    def setUp(self):
        factory_plans._jobs.clear()

    def test_a_topic_becomes_researched_plans_that_stay_until_made(self):
        with TempWorkspace() as ws:
            llm = ScriptedLLM({"planner": [answer(["How a load balancer picks a server", "Why health checks matter"])]})
            factory_plans.plan(ws, "load balancers", count=2, llm=llm, research=NO_RESEARCH, background=False)
            plans = factory_plans.view(ws)["plans"]
            self.assertEqual([p["title"] for p in sorted(plans, key=lambda p: p["title"])], ["How a load balancer picks a server", "Why health checks matter"])
            self.assertTrue(all(p["state"] == "planned" and p["topic"] == "load balancers" and p["format"] == "short" for p in plans))
            factory_plans._update(ws, plans[0]["id"], state="made")
            self.assertEqual(len(factory_plans.view(ws)["plans"]), 1)   # only a made plan leaves the list
            self.assertEqual(factory_plans.view(ws)["made"], 1)

    def test_the_whole_flow_is_by_hand(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            item = factory_plans.add_own(ws, "What a bloom filter is")
            factory_plans.write_script(ws, item["id"], "open with a bouncer at a club")
            wait(item["id"])
            item = factory_plans.get(ws, item["id"])
            self.assertEqual(item["state"], "script", item.get("error"))
            prompt = next(c[1]["input"] for c in calls if "claude" in c[0][0])
            self.assertIn("What a bloom filter is", prompt)
            self.assertIn("open with a bouncer at a club", prompt)                       # your instructions reach the writer
            self.assertFalse(any(c[0][:3] == ["npm", "run", "make"] for c in calls))      # the script run stops before the video
            ep = root / "episodes" / item["slug"]
            self.assertEqual(voice_desk.desk(ep)["plan_id"], item["id"])
            with self.assertRaises(ValueError):
                factory_plans.make(ws, item["id"])                                      # not approved yet
            voice_desk.approve_script(ws, item["slug"])
            voice_desk.choose(ws, item["slug"], "am_puck")
            self.assertEqual(factory_plans.get(ws, item["id"])["state"], "script")      # approving makes nothing by itself
            n_claude = sum(1 for c in calls if "claude" in c[0][0])
            factory_plans.make(ws, item["id"])
            wait(item["id"])
            item = factory_plans.get(ws, item["id"])
            self.assertEqual(item["state"], "made", item.get("error"))
            self.assertEqual(sum(1 for c in calls if "claude" in c[0][0]), n_claude)     # the approved script was used as it is
            self.assertTrue(any(c[0][:3] == ["npm", "run", "make"] for c in calls))
            self.assertEqual(len(ws.queue()), 1)
            self.assertEqual(json.loads((ep / "script.json").read_text())["voice"], "am_puck")
            self.assertEqual(factory_plans.view(ws)["plans"], [])

    def test_a_topic_is_needed(self):
        with TempWorkspace() as ws:
            with self.assertRaises(ValueError):
                factory_plans.plan(ws, " ", background=False)


if __name__ == "__main__":
    unittest.main()
