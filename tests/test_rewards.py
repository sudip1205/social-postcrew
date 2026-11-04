"""Rewards: approving or publishing earns the agents points, a veto costs them, and the best approved video becomes the model."""
import json
import unittest
from types import SimpleNamespace

from postcrew import rewards
from postcrew.agents.base import Agent

from helpers import TempWorkspace

SCENES = [{"part": "intro", "layout": "title", "on_screen": "Climb stairs, three ways", "narration": "Have you ever wondered how many ways"},
          {"part": "visual", "layout": "paths", "on_screen": "Four stairs", "narration": "Picture four stairs and a little figure",
           "direction": {"visual": "a staircase with every way up"}},
          {"part": "closing", "layout": "statement", "narration": "If this was useful, please like"}]


def make_run(ws, run_id, author="writer-nora", platform="youtube"):
    d = ws.runs_dir / run_id
    d.mkdir(parents=True)
    steps = {s: {"state": "passed"} for s in ("credentials", "topic", "research", "writer", "editor", "direction", "graphics", "voice",
                                              "media", "quality", "publisher")}
    steps["video_review"] = {"state": "skipped"}
    (d / "status.json").write_text(json.dumps({"steps": steps}))
    (d / "writer.json").write_text(json.dumps({"author": author, "scenes": [SCENES[0]]}))
    (d / "script.final.json").write_text(json.dumps({"title": "Climbing Stairs", "concept": "one staircase that grows", "scenes": SCENES}))
    return {"id": f"post-{run_id}", "run_id": run_id, "platform": platform, "topic": "Climbing Stairs", "category": "short",
            "youtube": {"format": "short", "seconds": 165}}


class RewardTests(unittest.TestCase):
    def test_approve_then_publish_is_one_reward(self):
        with TempWorkspace() as ws:
            post = make_run(ws, "r1")
            self.assertEqual(rewards.record(ws, post, "approved"), 10)
            self.assertEqual(rewards.record(ws, post, "published"), 0)
            a = rewards.load(ws)["agents"]
            self.assertEqual((a["writer"]["points"], a["writer"]["published"]), (10, 1))
            self.assertEqual(a["writer:writer-nora"]["points"], 10)          # the writer whose draft was chosen
            self.assertEqual(a["graphics"]["points"], 10)
            self.assertNotIn("credentials", a)                                # did not shape the work
            self.assertNotIn("video_review", a)                               # skipped

    def test_a_veto_replaces_the_reward_and_restore_takes_the_penalty_back(self):
        with TempWorkspace() as ws:
            post = make_run(ws, "r1")
            rewards.record(ws, post, "approved")
            self.assertEqual(rewards.record(ws, post, "vetoed", "the number runs off the screen"), -20)
            r = rewards.load(ws)["agents"]["writer"]
            self.assertEqual((r["points"], r["published"], r["vetoed"]), (-10, 0, 1))
            self.assertEqual(rewards.best_exemplar(ws), None)                # a vetoed video is not followed
            self.assertEqual(rewards.record(ws, post, "restored"), 10)
            r = rewards.load(ws)["agents"]["writer"]
            self.assertEqual((r["points"], r["vetoed"]), (0, 0))

    def test_the_best_approved_video_is_the_model_and_a_pinned_one_wins(self):
        with TempWorkspace() as ws:
            a, b = make_run(ws, "r1"), make_run(ws, "r2")
            b["topic"] = "Two Sum"
            rewards.record(ws, a, "approved")
            rewards.record(ws, b, "approved")
            self.assertEqual(rewards.best_exemplar(ws)["post"], "post-r2")    # newest of the equally rated
            rewards.pin(ws, "post-r1")
            self.assertEqual(rewards.best_exemplar(ws)["post"], "post-r1")
            rewards.pin(ws, "post-r2")
            self.assertEqual([e["post"] for e in rewards.exemplars(ws) if e["pinned"]], ["post-r2"])   # one pinned at a time
            self.assertIsNone(rewards.best_exemplar(ws, fmt="long"))

    def test_agents_read_their_record_vetoes_and_the_model(self):
        with TempWorkspace() as ws:
            good, bad = make_run(ws, "r1"), make_run(ws, "r2")
            bad["topic"] = "Big O in 30 seconds"
            rewards.record(ws, good, "approved")
            rewards.record(ws, bad, "vetoed", "too much text, nothing moves")
            ctx = SimpleNamespace(ws=ws, platform="youtube", video={"format": "short"}, category="short")
            writer = Agent._record_block(ctx, "writer", {"id": "writer-nora"})
            self.assertIn("+0 points, 1 published, 1 vetoed", writer)       # Nora's own record
            self.assertIn("too much text, nothing moves", writer)
            self.assertIn("BEST-RATED PUBLISHED VIDEO", writer)
            self.assertIn("visual / paths: Four stairs | shows a staircase with every way up", writer)
            editor = Agent._record_block(ctx, "editor")
            self.assertIn("VETOED BY THE OWNER", editor)
            self.assertNotIn("Scene by scene", editor)                        # only the agents that shape a video follow the model
            linkedin = SimpleNamespace(ws=ws, platform="linkedin", category="x")
            self.assertNotIn("Big O", Agent._record_block(linkedin, "writer"))  # YouTube vetoes are not LinkedIn's

    def test_an_owners_own_video_and_a_post_without_a_run_earn_nothing(self):
        with TempWorkspace() as ws:
            self.assertEqual(rewards.record(ws, {"id": "x", "platform": "youtube"}, "approved"), 0)
            post = make_run(ws, "r1")
            self.assertEqual(rewards.record(ws, dict(post, source="own"), "approved"), 0)
            self.assertEqual(Agent._record_block(SimpleNamespace(ws=ws, platform="youtube", video={}, category=None), "writer"), "")


if __name__ == "__main__":
    unittest.main()
