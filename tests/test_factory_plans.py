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
            from tests.test_voice_desk import _fake_generate
            _fake_generate(ws, item["slug"], "am_puck")      # the AI voice is generated and listened to before it is approved
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
            self.assertEqual(json.loads((ep / "script.json").read_text())["voice_kokoro"], "am_puck")   # the approved take, read by am_puck
            self.assertEqual(factory_plans.view(ws)["plans"], [])

    def test_a_plan_can_be_deleted_but_not_while_it_is_worked_on(self):
        with TempWorkspace() as ws:
            a = factory_plans.add_own(ws, "What a bloom filter is")
            b = factory_plans.add_own(ws, "How a CDN caches pages")
            factory_plans._update(ws, b["id"], state="writing")
            with self.assertRaises(ValueError):
                factory_plans.remove(ws, b["id"])
            factory_plans.remove(ws, a["id"])
            self.assertEqual([p["id"] for p in factory_plans.view(ws)["plans"]], [b["id"]])

    def _approved(self, ws, root, look):
        item = factory_plans.add_own(ws, "What a bloom filter is")
        ep = root / "episodes" / "bloom"
        ep.mkdir(parents=True)
        (ep / "script.json").write_text(json.dumps({"style": look, "beats": [{"say": "One."}, {"say": "Two."}]}))
        voice_desk._save_desk(ep, {"slug": "bloom", "script": "approved", "voice": {"state": "approved"},
                                   "writer": {"slug": "bloom", "style": "iso" if look in ("iso", "blue") else look, **({"look": look} if look in ("iso", "blue") else {})}})
        factory_plans._update(ws, item["id"], state="script", slug="bloom")
        return item

    def test_approved_plans_are_ready_to_make_in_a_look_that_keeps_the_voice(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            item = self._approved(ws, root, "iso")
            ready = factory_plans.ready(ws)
            self.assertEqual([r["id"] for r in ready], [item["id"]])
            self.assertEqual(ready[0]["look"], "iso")
            self.assertTrue(all(l["ok"] for l in ready[0]["looks"]))
            seen = []
            factory_plans.make(ws, item["id"], "blue", runner=lambda ws_, options, fmt: seen.append(options) or {"ok": True, "run_id": "r1"})
            wait(item["id"])
            self.assertEqual(seen[0]["restyle"], "blue")                 # drawn again in the new look
            self.assertNotIn("writer", seen[0]["kept"])                 # ... by the writer, which keeps the approved words
            self.assertEqual(factory_plans.get(ws, item["id"])["made_look"], "blue")

    def test_the_same_look_uses_the_approved_script_as_it_is(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            item = self._approved(ws, root, "blue")
            seen = []
            factory_plans.make(ws, item["id"], "blue", runner=lambda ws_, options, fmt: seen.append(options) or {"ok": True, "run_id": "r1"})
            wait(item["id"])
            self.assertIn("writer", seen[0]["kept"])
            self.assertNotIn("restyle", seen[0])

    def test_a_scene_script_cannot_be_switched_to_a_canvas_look(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            item = self._approved(ws, root, "signal")
            looks = {l["id"]: l["ok"] for l in factory_plans.ready(ws)[0]["looks"]}
            self.assertEqual(looks, {"signal": True, "iso": False, "blue": False})
            with self.assertRaises(ValueError):
                factory_plans.make(ws, item["id"], "iso")

    def test_a_topic_is_needed(self):
        with TempWorkspace() as ws:
            with self.assertRaises(ValueError):
                factory_plans.plan(ws, " ", background=False)


if __name__ == "__main__":
    unittest.main()


class RestyleTests(unittest.TestCase):
    def test_a_redraw_keeps_every_approved_word_and_the_desk_approvals(self):
        from types import SimpleNamespace
        from postcrew.agents.shorts import ShortsWriter
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            ep = root / "episodes" / "bloom"
            ep.mkdir(parents=True)
            (ep / "script.json").write_text(json.dumps({"style": "iso", "hook_options": ["a", "b", "c"], "beats": [{"say": "One."}, {"say": "Two."}]}))
            voice_desk._save_desk(ep, {"slug": "bloom", "script": "approved", "voice": {"state": "approved"}, "writer": {"look": "iso"}})
            w = ShortsWriter()

            def plan_iso(ctx, root_, ep_, slug, subject, topic, guidance=None, look="iso"):
                self.assertIn("do not change", guidance[0])
                (ep_ / "script.json").write_text(json.dumps({"style": "blue", "beats": [{"say": "One, edited."}, {"say": "Two."}]}))
                return {"slug": slug, "episode": str(ep_), "title": "t", "look": look, "style": "iso"}
            w._plan_iso = plan_iso
            ctx = SimpleNamespace(ws=ws, outputs={"topic": {"topic": "Bloom"}}, options={})
            out = w._restyle(ctx, root, "bloom", "blue")
            script = json.loads((ep / "script.json").read_text())
            self.assertEqual([b["say"] for b in script["beats"]], ["One.", "Two."])
            self.assertEqual(script["style"], "blue")
            self.assertEqual(script["hook_options"], ["a", "b", "c"])
            d = voice_desk.desk(ep)
            self.assertEqual((d["script"], d["voice"]["state"], d["writer"]["look"]), ("approved", "approved", "blue"))
            self.assertTrue(out["reused"])
