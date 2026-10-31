"""The monthly plan: topics become a pool of plans, you assign them to days, published plans are never planned again."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from helpers import ScriptedLLM, TempWorkspace  # noqa: E402

from postcrew import monthly  # noqa: E402
from postcrew.agents import planner  # noqa: E402
from postcrew import scheduler  # noqa: E402
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
            self.assertEqual([x["title"] for x in v["days"]["2026-11-10"]], [item["title"]])
            other = v["items"][1]
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

    def assigned(self, ws, n, day="2026-11-10", fmt=None):
        monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:10])]}), today=TODAY)
        items = monthly.view(ws, "linkedin", "2026-11", TODAY)["items"][:n]
        for it in items:
            monthly.assign(ws, "linkedin", it["id"], day, today=TODAY)
        return items

    def test_a_day_holds_several_plans_and_the_first_is_the_one_made(self):
        with TempWorkspace() as ws:
            self.ws(ws)
            a, b, c = self.assigned(ws, 3)
            days = monthly.view(ws, "linkedin", "2026-11", TODAY)["days"]["2026-11-10"]
            self.assertEqual([(x["id"], x["position"], x["of"]) for x in days], [(a["id"], 1, 3), (b["id"], 2, 3), (c["id"], 3, 3)])
            self.assertEqual(planner.load_plan(ws)["2026-11-10"]["plan_id"], a["id"])             # the scheduled run takes this one
            self.assertEqual(planner.plan_id_for(ws, "linkedin", "2026-11-10", ws.config()["schedule"]["dates"][0]["category"]), a["id"])
            self.assertEqual(len(ws.config()["schedule"]["dates"]), 1)                              # still one entry for the day

    def test_a_published_plan_leaves_the_calendar_stays_struck_in_the_list_and_the_next_one_is_current(self):
        with TempWorkspace() as ws:
            self.ws(ws)
            a, b = self.assigned(ws, 2)
            ws.add_history({"id": "p1", "date": "2026-11-10", "topic": "A title the Script Writer rewrote", "platform": "linkedin", "plan_id": a["id"]})
            monthly.sync_all(ws, "linkedin")                                  # what a run, a scheduler tick and the Plan page do first
            v = monthly.view(ws, "linkedin", "2026-11", TODAY)               # found by its plan id, not by its (rewritten) title
            self.assertEqual([x["id"] for x in v["days"]["2026-11-10"]], [b["id"]])
            self.assertEqual([i["status"] for i in v["items"][:2]], ["published", "assigned"])
            self.assertEqual(planner.load_plan(ws)["2026-11-10"]["plan_id"], b["id"])               # the next one is what a run makes now
            with self.assertRaises(ValueError):
                monthly.assign(ws, "linkedin", a["id"], "2026-11-12", today=TODAY)                  # never planned again
            c = v["items"][2]
            monthly.assign(ws, "linkedin", c["id"], "2026-11-10", today=TODAY)                      # one more on the same day
            self.assertEqual([x["id"] for x in monthly.view(ws, "linkedin", "2026-11", TODAY)["days"]["2026-11-10"]], [b["id"], c["id"]])

    def test_when_every_plan_of_a_day_is_published_the_day_leaves_the_schedule(self):
        with TempWorkspace() as ws:
            self.ws(ws)
            (a,) = self.assigned(ws, 1)
            ws.add_history({"id": "p1", "date": "2026-11-10", "topic": a["title"], "platform": "linkedin", "plan_id": a["id"]})
            monthly.sync_all(ws, "linkedin")
            self.assertEqual((ws.config()["schedule"]["dates"], planner.load_plan(ws)), ([], {}))
            self.assertEqual(monthly.view(ws, "linkedin", "2026-11", TODAY)["days"], {})

    def test_the_scheduled_run_makes_one_post_a_day_and_a_manual_run_makes_the_next(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with TempWorkspace() as ws:
            self.ws(ws)
            a, b = self.assigned(ws, 2, "2026-11-04")
            calls = []
            noop = lambda *x, **k: None
            tz = ZoneInfo(ws.config()["schedule"]["timezone"])
            # the evening before: the scheduler makes the day's post, once
            for hour in (19, 20):
                scheduler.tick(ws, datetime(2026, 11, 3, hour, 5, tzinfo=tz), runner=lambda w, d: calls.append((d.isoformat(), planner.load_plan(w)[d.isoformat()]["plan_id"])),
                               publisher=noop, checker=noop, planner=noop, cleaner=noop)
            self.assertEqual(calls, [("2026-11-04", a["id"])])
            # that post is published; the scheduler does not start a second one for the day
            ws.add_history({"id": "p1", "date": "2026-11-04", "topic": a["title"], "platform": "linkedin", "plan_id": a["id"], "published_at": "x"})
            scheduler.tick(ws, datetime(2026, 11, 3, 21, 0, tzinfo=tz), runner=lambda w, d: calls.append("again"), publisher=noop, checker=noop, planner=noop, cleaner=noop)
            self.assertEqual(len(calls), 1)
            # a manual run (run_crew) now takes the next plan
            from postcrew import crew
            seen = []
            from unittest import mock
            with mock.patch("postcrew.crew.Supervisor") as sup:
                sup.return_value.run.side_effect = lambda ctx: seen.append(planner.planned_for(ws, ctx.day, ctx.category)["plan_id"]) or {"ok": True}
                crew.run_crew(ws, date(2026, 11, 4), llm=ScriptedLLM({}))
            self.assertEqual(seen, [b["id"]])

    def test_at_most_five_plans_wait_on_one_day_and_a_written_plan_cannot_be_unassigned(self):
        with TempWorkspace() as ws:
            self.ws(ws)
            monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:10])]}), today=TODAY)
            items = monthly.view(ws, "linkedin", "2026-11", TODAY)["items"]
            for it in items[:5]:
                monthly.assign(ws, "linkedin", it["id"], "2026-11-10", today=TODAY)
            with self.assertRaises(ValueError):
                monthly.assign(ws, "linkedin", items[5]["id"], "2026-11-10", today=TODAY)
            ws.save_queue([{"id": "q1", "platform": "linkedin", "date": "2026-11-10", "status": "awaiting_approval", "topic": "x", "plan_id": items[0]["id"]}])
            with self.assertRaises(ValueError):
                monthly.unassign(ws, "linkedin", items[0]["id"])
            monthly.unassign(ws, "linkedin", items[1]["id"])                                         # a waiting one can go
            self.assertEqual(len(monthly.view(ws, "linkedin", "2026-11", TODAY)["days"]["2026-11-10"]), 4)

    def test_two_posts_of_one_day_keep_their_own_queue_entries(self):
        from postcrew import platforms
        from postcrew.agents import publisher
        with TempWorkspace() as ws:
            self.ws(ws)
            a, b = self.assigned(ws, 2)
            cfg = platforms.view(ws.config(), "linkedin")
            cat = ws.config()["schedule"]["dates"][0]["category"]
            final = lambda t: {"title": t, "text": "body text"}
            publisher.enqueue(ws, cfg, "r1", date(2026, 11, 10), cat, final("First"), {})
            ws.add_history({"id": "p1", "date": "2026-11-10", "topic": "First", "platform": "linkedin", "plan_id": a["id"]})   # published; B is current
            monthly.sync_all(ws, "linkedin")
            ws.save_queue([])
            publisher.enqueue(ws, cfg, "r2", date(2026, 11, 10), cat, final("Second"), {})
            q = ws.queue()
            self.assertEqual(len(q), 1)
            self.assertEqual(q[0]["plan_id"], b["id"])
            self.assertTrue(q[0]["id"].endswith("-" + b["id"]))

    def test_no_topics_means_no_plan_and_a_clear_message(self):
        with TempWorkspace() as ws:
            with self.assertRaises(ValueError) as cm:
                monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({}), today=TODAY)
            self.assertIn("Settings", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


class AssignedLengthTests(unittest.TestCase):
    def test_an_assigned_short_is_never_shorter_than_fifty_seconds_and_old_ones_are_fixed(self):
        from postcrew import monthly
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"]["enabled"] = True
            ws.save_config(cfg)
            cid = monthly.category_for_item(ws, "youtube", "short")
            self.assertEqual(ws.config()["platforms"]["youtube"]["categories"][cid]["target_seconds"], 75)
            cfg = ws.config()
            cfg["platforms"]["youtube"]["categories"][cid]["target_seconds"] = 45       # made by an earlier version
            ws.root.joinpath("config.json").write_text(__import__("json").dumps(cfg))
            monthly.category_for_item(ws, "youtube", "short")
            self.assertEqual(ws.config()["platforms"]["youtube"]["categories"][cid]["target_seconds"], 75)
            self.assertEqual(monthly.category_for_item(ws, "youtube", "long"), "assigned-long")
            self.assertEqual(ws.config()["platforms"]["youtube"]["categories"]["assigned-long"]["target_seconds"], 480)
