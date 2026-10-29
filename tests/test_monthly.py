"""The monthly plan: topics become a pool of plans, you assign them to days, published plans are never planned again."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from helpers import ScriptedLLM, TempWorkspace  # noqa: E402

from postcrew import monthly  # noqa: E402
from postcrew.agents import planner  # noqa: E402
from postcrew.scheduler import tick  # noqa: E402

TODAY = date(2026, 11, 3)
TITLES = ["Circuit breaker states", "Retries without storms", "Bulkheads in practice", "Timeouts that fit", "Fallbacks users accept",
          "Half-open probes", "Metrics for breakers", "Breakers vs rate limits", "Testing failure paths", "Breakers in service meshes",
          "Library choices for breakers", "Tuning thresholds"]


def plan(title, n=0):
    return {"title": title, "angle": f"what to know about {title}", "context": "why it matters", "example": f"a service calling {n}",
            "takeaway": "do this", "search_queries": [f"{title} guide"]}


def answer(titles):
    return {"plans": [plan(t, i) for i, t in enumerate(titles)]}


class MonthlyTests(unittest.TestCase):
    def ws(self, ws, topics=("Circuit breaker pattern",)):
        cfg = ws.config()
        cfg["topics"] = list(topics)
        cfg["schedule"].update(frequency="dates", days={})      # the app as it is now: only assigned days post
        ws.save_config(cfg)

    def test_a_topic_gets_ten_plans_that_are_not_on_any_day(self):
        with TempWorkspace() as ws:
            self.ws(ws)
            llm = ScriptedLLM({"planner": [answer(TITLES[:10])]})
            out = monthly.generate(ws, "linkedin", "2026-11", llm=llm, today=TODAY)
            self.assertEqual(out["added"], 10)
            v = monthly.view(ws, "linkedin", "2026-11", TODAY)
            self.assertEqual((v["counts"]["plans"], v["counts"]["unassigned"], v["days"]), (10, 10, {}))
            self.assertEqual(planner.load_plan(ws), {})                       # nothing was put on a day
            self.assertEqual(monthly.generate(ws, "linkedin", "2026-11", llm=llm, today=TODAY)["added"], 0)   # already full

    def test_repeats_are_sent_back_and_never_kept(self):
        with TempWorkspace() as ws:
            self.ws(ws)
            ws.add_history({"date": "2026-10-01", "topic": "Circuit breaker states"})
            llm = ScriptedLLM({"planner": [answer(TITLES[:10]), answer(TITLES[10:12] + TITLES[1:2])]})
            out = monthly.generate(ws, "linkedin", "2026-11", llm=llm, today=TODAY)
            titles = [i["title"] for i in monthly.view(ws, "linkedin", "2026-11", TODAY)["items"]]
            self.assertNotIn("Circuit breaker states", titles)                # published before
            self.assertEqual(len(titles), len(set(titles)))
            self.assertIn("repeats", llm.calls[1]["prompt"])
            self.assertEqual(out["added"], len(titles))

    def test_assign_moves_a_plan_onto_a_day_and_the_scheduler_follows(self):
        with TempWorkspace() as ws:
            self.ws(ws)
            monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:10])]}), today=TODAY)
            item = monthly.view(ws, "linkedin", "2026-11", TODAY)["items"][0]
            monthly.assign(ws, "linkedin", item["id"], "2026-11-10", today=TODAY)
            e = planner.load_plan(ws)["2026-11-10"]
            self.assertEqual((e["topic"], e["source"], e["plan_id"]), (item["title"], "manual", item["id"]))
            self.assertEqual(e["brief"]["context"], "why it matters")
            from postcrew import platforms
            self.assertTrue(platforms.category_for(ws.config()["schedule"], "2026-11-10"))
            self.assertIsNone(platforms.category_for(ws.config()["schedule"], "2026-11-11"))   # only assigned days post
            v = monthly.view(ws, "linkedin", "2026-11", TODAY)
            self.assertEqual(v["days"]["2026-11-10"]["title"], item["title"])
            other = v["items"][1]
            with self.assertRaises(ValueError):                                # one plan per day
                monthly.assign(ws, "linkedin", other["id"], "2026-11-10", today=TODAY)
            with self.assertRaises(ValueError):                                # not in the past
                monthly.assign(ws, "linkedin", other["id"], "2026-11-02", today=TODAY)
            monthly.assign(ws, "linkedin", item["id"], "2026-11-12", today=TODAY)   # moving frees the old day
            self.assertEqual(sorted(planner.load_plan(ws)), ["2026-11-12"])
            monthly.unassign(ws, "linkedin", item["id"])
            self.assertEqual((planner.load_plan(ws), ws.config()["schedule"]["dates"]), ({}, []))

    def test_youtube_plans_are_assigned_as_short_or_long(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"]["topics"] = ["OAuth 2.0 and PKCE"]
            ws.save_config(cfg)
            monthly.generate(ws, "youtube", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:10])]}), today=TODAY)
            a, b = monthly.view(ws, "youtube", "2026-11", TODAY)["items"][:2]
            monthly.assign(ws, "youtube", a["id"], "2026-11-10", "short", TODAY)
            monthly.assign(ws, "youtube", b["id"], "2026-11-11", "long", TODAY)
            plan_ = planner.load_plan(ws, "youtube")
            self.assertEqual((plan_["2026-11-10"]["format"], plan_["2026-11-11"]["format"]), ("short", "long"))
            cats = ws.config()["platforms"]["youtube"]["categories"]
            self.assertEqual((cats["assigned-short"]["format"], cats["assigned-long"]["format"]), ("short", "long"))
            self.assertEqual(plan_["2026-11-10"]["category"], "assigned-short")
            with self.assertRaises(ValueError):
                monthly.assign(ws, "youtube", a["id"], "2026-11-12", "medium", TODAY)

    def test_a_published_plan_stays_listed_and_cannot_be_assigned_again(self):
        with TempWorkspace() as ws:
            self.ws(ws)
            monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:10])]}), today=TODAY)
            item = monthly.view(ws, "linkedin", "2026-11", TODAY)["items"][0]
            ws.add_history({"date": "2026-11-03", "topic": item["title"], "platform": "linkedin"})
            v = monthly.view(ws, "linkedin", "2026-11", TODAY)
            self.assertEqual((v["items"][0]["status"], v["counts"]["published"]), ("published", 1))
            with self.assertRaises(ValueError):
                monthly.assign(ws, "linkedin", item["id"], "2026-11-20", today=TODAY)

    def test_the_scheduler_writes_the_month_once_from_the_current_topics(self):
        with TempWorkspace() as ws:
            self.ws(ws, ("Circuit breaker pattern",))
            calls = []
            planner_fn = lambda w, d, platform="linkedin": calls.append((d.isoformat(), platform))
            noop = lambda *a, **k: None
            from datetime import datetime
            from zoneinfo import ZoneInfo
            now = datetime(2026, 11, 1, 7, 0, tzinfo=ZoneInfo("America/Chicago"))
            did = tick(ws, now, runner=noop, publisher=noop, checker=noop, planner=planner_fn)
            self.assertIn("plan 2026-11", did)
            self.assertEqual(tick(ws, now, runner=noop, publisher=noop, checker=noop, planner=planner_fn).count("plan 2026-11"), 0)
            self.ws(ws, ("Circuit breaker pattern", "OAuth 2.0 and PKCE"))      # a topic added mid-month waits for next month
            tick(ws, now.replace(day=15), runner=noop, publisher=noop, checker=noop, planner=planner_fn)
            self.assertEqual(len(calls), 1)
            tick(ws, now.replace(month=12), runner=noop, publisher=noop, checker=noop, planner=planner_fn)
            self.assertEqual([c[0] for c in calls], ["2026-11-01", "2026-12-01"])

    def test_two_generations_at_once_write_the_plans_once(self):
        import threading
        import time

        class Slow(ScriptedLLM):
            def call(self, *a, **k):
                time.sleep(0.2)
                return super().call(*a, **k)
        with TempWorkspace() as ws:
            self.ws(ws)
            llm = Slow({"planner": [answer(TITLES[:10])]})
            threads = [threading.Thread(target=monthly.generate, args=(ws, "linkedin", "2026-11", llm, TODAY)) for _ in range(2)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(monthly.view(ws, "linkedin", "2026-11", TODAY)["counts"]["plans"], 10)
            self.assertEqual(len(llm.calls), 1)

    def test_no_topics_means_no_plan_and_a_clear_message(self):
        with TempWorkspace() as ws:
            with self.assertRaises(ValueError) as cm:
                monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({}), today=TODAY)
            self.assertIn("Settings", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
