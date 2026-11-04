"""Your own plans (Manual run) reach every agent that shapes the video, and YouTube analytics read the connected channel."""
import unittest
from datetime import date
from types import SimpleNamespace

from postcrew import monthly, yt_analytics
from postcrew.agents.base import owner_plan_block
from postcrew.youtube import YouTubeError, _duration

from helpers import TempWorkspace

DAY = date(2026, 11, 4)


class OwnPlanTests(unittest.TestCase):
    def test_a_plan_you_write_waits_for_you_and_survives_generate_and_pruning(self):
        with TempWorkspace() as ws:
            i = monthly.add_manual(ws, "youtube", "Dijkstra on a city map", "Shortest path. Use 5 junctions.",
                                   "Animate each step, code beside it.", "long", references=["https://example.com/d"], today=DAY)
            self.assertTrue(i["manual"])
            self.assertEqual((i["angle"], i["format"]), ("Shortest path.", "long"))
            ids = [u["id"] for u in monthly.unassigned(ws, "youtube")]
            self.assertIn(i["id"], ids)
            monthly.clear_plans(ws, "youtube")                    # Generate plan starts clean, but not with your plans
            monthly.prune_stale_topics(ws, "youtube")             # "Your own plans" is not a Settings topic
            self.assertEqual(monthly.auto_assign(ws, "youtube", "2026-11", today=DAY)["assigned"], 0)   # never put on a day by itself
            self.assertIn(i["id"], [u["id"] for u in monthly.unassigned(ws, "youtube")])
            monthly.add_manual(ws, "youtube", "Dijkstra on a city map", "Shortest path.", "Slower, calmer.", "short", item_id=i["id"])
            self.assertEqual(next(u for u in monthly.unassigned(ws, "youtube") if u["id"] == i["id"])["how"], "Slower, calmer.")
            monthly.remove_manual(ws, "youtube", i["id"])
            self.assertNotIn(i["id"], [u["id"] for u in monthly.unassigned(ws, "youtube")])

    def test_bad_input_is_refused(self):
        with TempWorkspace() as ws:
            for args in (("ab",), ("Good topic", "x" * 3001), ("Good topic", "", "", "medium")):
                with self.assertRaises(ValueError):
                    monthly.add_manual(ws, "youtube", *args)
            with self.assertRaises(ValueError):
                monthly.add_manual(ws, "youtube", "Good topic", references=["not a link"])

    def test_running_it_carries_your_plan_to_the_agents_that_shape_the_video(self):
        with TempWorkspace() as ws:
            i = monthly.add_manual(ws, "youtube", "Dijkstra on a city map", "Use 5 junctions.", "Animate each step.", "short", today=DAY)
            info = monthly.run_plan(ws, "youtube", i["id"], "short", DAY)
            self.assertEqual(info["item"]["id"], i["id"])
            e = monthly._entry(dict(i, assigned={"date": DAY.isoformat()}), "assigned-short", "short", "youtube")
            self.assertEqual(e["owner_plan"]["how"], "Animate each step.")
            self.assertEqual(e["brief"]["context"], "Use 5 junctions.")
            ctx = SimpleNamespace(outputs={"topic": {"owner_plan": e["owner_plan"]}})
            for agent in ("writer", "direction", "graphics", "editor", "quality"):
                self.assertIn("Animate each step.", owner_plan_block(ctx, agent))
            self.assertEqual(owner_plan_block(ctx, "publisher"), "")
            self.assertEqual(owner_plan_block(SimpleNamespace(outputs={}), "writer"), "")


class FakeYT:
    deny = False

    def __init__(self, *a):
        pass

    def channel_stats(self):
        return {"id": "UC1", "title": "Dip-to-Dive", "subscribers": 120, "views": 5000, "videos": 2, "uploads": "UU1"}

    def uploads(self, playlist, limit=200):
        return ["v1", "v2"]

    def videos(self, ids):
        return [{"id": "v1", "title": "Climbing Stairs", "published_at": "2026-11-03T18:00:00Z", "seconds": 150, "views": 900, "likes": 40,
                 "comments": 5, "privacy": "public", "thumbnail": ""},
                {"id": "v2", "title": "My own upload", "published_at": "2026-10-01T18:00:00Z", "seconds": 900, "views": 100, "likes": 2,
                 "comments": 0, "privacy": "public", "thumbnail": ""}]

    def report(self, start, end, metrics, dimensions="", sort="", filters="", limit=200):
        if FakeYT.deny:
            raise YouTubeError("YouTube refused access (Request had insufficient authentication scopes.): reconnect", "auth", 403)
        if dimensions == "video":
            return [{"video": "v1", "views": 900, "estimatedMinutesWatched": 1200, "averageViewDuration": 80, "averageViewPercentage": 53.3,
                     "likes": 40, "comments": 5, "shares": 3, "subscribersGained": 9}]
        return [{"day": "2026-11-03", "views": 700, "estimatedMinutesWatched": 900, "subscribersGained": 8, "subscribersLost": 1}]


class AnalyticsTests(unittest.TestCase):
    def connect(self, ws):
        ws.update_secrets(youtube_client_id="1-a.apps.googleusercontent.com", youtube_client_secret="s", youtube_refresh_token="r")
        ws.add_history({"id": "p1", "platform": "youtube", "topic": "Climbing Stairs", "run_id": "r1",
                        "youtube": {"video_id": "v1", "format": "short", "picture": {"score": 82}}})

    def test_every_video_with_the_crews_marked_and_their_watch_time(self):
        with TempWorkspace() as ws:
            self.connect(ws)
            FakeYT.deny = False
            d = yt_analytics.build(ws, FakeYT, today=date(2026, 11, 4))
            self.assertEqual(d["channel"]["title"], "Dip-to-Dive")
            v1, v2 = d["videos"]
            self.assertEqual((v1["crew"]["post_id"], v1["format"], v1["analytics"]["averageViewPercentage"]), ("p1", "short", 53.3))
            self.assertIsNone(v2["crew"])
            self.assertEqual(v2["format"], "long")
            self.assertEqual((d["summary"]["crew_videos"], d["summary"]["crew_views"], d["summary"]["crew_minutes"]), (1, 900, 1200))
            self.assertEqual(d["analytics"]["daily"][0]["views"], 700)

    def test_an_older_connection_still_shows_the_counts_and_says_how_to_get_the_rest(self):
        with TempWorkspace() as ws:
            self.connect(ws)
            FakeYT.deny = True
            d = yt_analytics.overview(ws, FakeYT, refresh=True)
            self.assertFalse(d["analytics"]["ok"])
            self.assertIn("reconnect YouTube", d["analytics"]["message"])
            self.assertEqual(d["videos"][0]["views"], 900)
            FakeYT.deny = False
            self.assertTrue(yt_analytics.overview(ws, FakeYT)["cached"])          # fresh for 30 minutes

    def test_not_connected_and_durations(self):
        with TempWorkspace() as ws:
            self.assertFalse(yt_analytics.build(ws, FakeYT)["connected"])
        self.assertEqual((_duration("PT2M30S"), _duration("PT1H"), _duration("P0D"), _duration("bad")), (150, 3600, 0, None))


if __name__ == "__main__":
    unittest.main()
