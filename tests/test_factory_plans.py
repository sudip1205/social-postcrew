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

    def test_an_iso_drawing_from_before_the_label_rules_is_drawn_again(self):
        # owner 2026-11-22/23: names printed on objects; a video made from an older drawing still had overlapping floating chips
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            item = self._approved(ws, root, "iso")
            (root / "episodes" / "bloom" / "explainer.js").write_text("function explainer(ctx){ tag(ctx, 1, 2, 'Server 1'); }")
            seen = []
            factory_plans.make(ws, item["id"], "iso", runner=lambda ws_, options, fmt: seen.append(options) or {"ok": True, "run_id": "r1"})
            wait(item["id"])
            self.assertEqual(seen[0]["restyle"], "iso")                  # same look, drawn again to the new rules
            self.assertNotIn("writer", seen[0]["kept"])

    def test_an_iso_drawing_with_printed_names_is_used_as_it_is(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            item = self._approved(ws, root, "iso")
            (root / "episodes" / "bloom" / "explainer.js").write_text("function explainer(ctx){ nameOn(ctx, P, [0,0,0,2,2,2], 'Server 1'); }")
            seen = []
            factory_plans.make(ws, item["id"], "iso", runner=lambda ws_, options, fmt: seen.append(options) or {"ok": True, "run_id": "r1"})
            wait(item["id"])
            self.assertNotIn("restyle", seen[0])
            self.assertIn("writer", seen[0]["kept"])

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


class RecoveryAndLookTests(unittest.TestCase):
    def test_a_plan_cut_off_by_a_restart_goes_back_with_the_reason(self):
        with TempWorkspace() as ws:
            item = factory_plans.add_own(ws, "Playlists with linked lists")
            factory_plans._update(ws, item["id"], state="writing")
            factory_plans._jobs.pop(item["id"], None)
            notes = factory_plans.recover(ws)
            got = factory_plans.get(ws, item["id"])
            self.assertEqual(got["state"], "planned")
            self.assertIn("restarted", got["error"])
            self.assertEqual(len(notes), 1)

    def test_an_iso_script_stays_iso_when_signal_is_ticked(self):
        """Owner, 2026-11-25: a Signal tick had turned an approved Isometric script into Tech Glow; Isometric stays Isometric."""
        from postcrew import factory_styles
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            item = FactoryPlanTests._approved(self, ws, root, "iso")
            factory_styles.save(ws, ["signal"])
            self.assertEqual(factory_plans.ready(ws)[0]["want"], "iso")
            seen = []
            factory_plans.make(ws, item["id"], runner=lambda ws_, options, fmt: seen.append(options) or {"ok": True, "run_id": "r"})
            wait(item["id"])
            self.assertNotIn("restyle", seen[0])


class PublishAndDeleteTests(unittest.TestCase):
    """Owner, 2026-11-18: publish from the Factory (no Queue step); deleting a plan's video puts the plan back to make again."""
    def _made(self, ws, root):
        from postcrew import factory_chat
        item = FactoryPlanTests._approved(self, ws, root, "iso")
        factory_plans._update(ws, item["id"], state="made")
        ep = root / "episodes" / "bloom"
        (ep / "youtube.json").write_text(json.dumps({"title": "Bloom filters in 70 seconds", "description": "Why.", "tags": ["cs"]}))
        d = voice_desk.desk(ep); d["run"] = {"id": "run-7", "state": "done"}; voice_desk._save_desk(ep, d)
        (root / "out").mkdir(exist_ok=True)
        (root / "out" / "bloom-hyperframes.mp4").write_bytes(b"mp4")
        ws.save_queue([{"id": "q1", "platform": "youtube", "status": "awaiting_approval", "run_id": "run-7", "youtube": {"title": "Old"}}])
        return item, factory_chat

    def test_deleting_the_video_puts_the_plan_back_and_drops_its_queue_copy(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            item, factory_chat = self._made(ws, root)
            factory_chat.delete_video(ws, "bloom")
            self.assertEqual(factory_plans.get(ws, item["id"])["state"], "script")
            self.assertEqual(ws.queue(), [])
            self.assertEqual([r["id"] for r in factory_plans.ready(ws)], [item["id"]])   # make it again, in the look you pick

    def test_publish_uses_the_queue_copy_and_marks_the_plan_published(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            item, factory_chat = self._made(ws, root)
            sent = []
            def fake_publish(ws_, post):
                sent.append(post)
                return dict(post, status="published", url="https://youtu.be/x")
            with mock.patch("postcrew.agents.publisher.publish_post", fake_publish):
                factory_chat.publish_video(ws, "bloom", title="Bloom filters, fast", description="Why.", tags="cs, data")
            self.assertEqual(sent[0]["id"], "q1")
            self.assertEqual(sent[0]["youtube"]["title"], "Bloom filters, fast")
            self.assertEqual(ws.queue(), [])
            self.assertEqual(factory_plans.get(ws, item["id"])["state"], "published")
            self.assertFalse((root / "out" / "bloom-hyperframes.mp4").exists())


class RestyleFailureTests(unittest.TestCase):
    def test_a_failed_redraw_leaves_the_approved_lines(self):
        from types import SimpleNamespace
        from postcrew.agents.base import AgentError
        from postcrew.agents.shorts import ShortsWriter
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            ep = root / "episodes" / "bloom"
            ep.mkdir(parents=True)
            (ep / "script.json").write_text(json.dumps({"style": "iso", "beats": [{"say": "One."}, {"say": "Two."}, {"say": "Three."}]}))
            voice_desk._save_desk(ep, {"slug": "bloom", "script": "approved", "voice": {"state": "approved"}, "writer": {"look": "iso"}})
            w = ShortsWriter()
            def cut(ctx, root_, ep_, slug, subject, topic, guidance=None, look="iso"):
                (ep_ / "script.json").write_text(json.dumps({"style": "blue", "beats": [{"say": "One and two."}]}))
                return {"slug": slug}
            w._plan_iso = cut
            ctx = SimpleNamespace(ws=ws, outputs={"topic": {}}, options={})
            with self.assertRaises(AgentError):
                w._restyle(ctx, root, "bloom", "blue")
            beats = [b["say"] for b in json.loads((ep / "script.json").read_text())["beats"]]
            self.assertEqual(beats, ["One.", "Two.", "Three."])
            self.assertEqual(voice_desk.desk(ep)["approved_beats"], ["One.", "Two.", "Three."])


class PlanTagsTests(unittest.TestCase):
    """Owner, 2026-11-21: YouTube tags written with every plan, listed on it, editable, and carried into youtube.json."""

    def test_tags_are_cleaned_merged_and_kept_within_youtubes_limit(self):
        from postcrew import yt_tags
        self.assertEqual(yt_tags.clean(["#Egg Drop", "egg drop", ' "dp" ', "", "x" * 40]), ["egg drop", "dp"])
        many = [f"tag number {i}" for i in range(80)]
        self.assertLessEqual(yt_tags._size(yt_tags.clean(many)), yt_tags.MAX_CHARS)
        self.assertEqual(yt_tags.merge(["a b", "c"], ["c", "d"]), ["a b", "c", "d"])
        self.assertEqual(yt_tags.competitors([{"tags": ["Wifi", "router"]}, {"tags": ["wifi"]}])[0], "wifi")
        self.assertTrue(yt_tags.problems(["one", "two"]))
        self.assertEqual(yt_tags.problems([f"egg drop {i}" for i in range(12)]), [])

    def test_a_plans_tags_can_be_saved_or_written_and_reach_the_script(self):
        from postcrew import factory_plans, voice_desk
        from types import SimpleNamespace
        import tempfile
        with TempWorkspace() as ws, tempfile.TemporaryDirectory() as d, mock.patch.object(voice_desk, "_root", return_value=Path(d)):
            item = factory_plans.add_own(ws, "The egg drop puzzle", "2 eggs, 100 floors")
            self.assertEqual(factory_plans.set_tags(ws, item["id"], "Egg Drop, #dynamic programming, egg drop")["tags"],
                             ["egg drop", "dynamic programming"])
            fake = SimpleNamespace(call=lambda *a, **k: SimpleNamespace(data={"tags": [f"egg drop puzzle {i}" for i in range(15)]}))
            ep = voice_desk._root(ws) / "episodes" / "egg"; ep.mkdir(parents=True)
            (ep / "youtube.json").write_text(json.dumps({"title": "t", "tags": ["old tag"]}))
            factory_plans._update(ws, item["id"], slug="egg")
            got = factory_plans.set_tags(ws, item["id"], llm=fake)["tags"]
            self.assertEqual(len(got), 15)
            tags = json.loads((ep / "youtube.json").read_text())["tags"]
            self.assertEqual(tags[0], "egg drop puzzle 0"); self.assertEqual(tags[-1], "old tag")
            with self.assertRaises(ValueError):
                factory_plans.set_tags(ws, item["id"], " , #")
