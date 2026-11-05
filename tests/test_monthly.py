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

    def test_a_post_made_by_hand_or_your_own_plan_does_not_use_up_the_days_scheduled_run(self):
        # 2026-11-04: the REST API plan was made by hand at 00:28 and two of your own plans were run that day, so "a post for that date
        # exists" and the scheduled run never made the day's other plan (Kadane's)
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with TempWorkspace() as ws:
            self.ws(ws)
            a, b = self.assigned(ws, 2, "2026-11-04")
            ws.add_history({"id": "p1", "date": "2026-11-04", "topic": a["title"], "platform": "linkedin", "plan_id": a["id"], "published_at": "x"})
            own = monthly.add_manual(ws, "linkedin", "My own topic", "details")
            monthly.run_plan(ws, "linkedin", own["id"], None, today=date(2026, 11, 4))
            ws.save_queue([{"id": "p2", "date": "2026-11-04", "topic": "My own topic", "platform": "linkedin", "plan_id": own["id"],
                            "status": "awaiting_approval"}])
            calls, noop = [], (lambda *x, **k: None)
            tz = ZoneInfo(ws.config()["schedule"]["timezone"])
            for hour in (19, 20):
                scheduler.tick(ws, datetime(2026, 11, 3, hour, 5, tzinfo=tz), runner=lambda w, d: calls.append((d.isoformat(), planner.load_plan(w)[d.isoformat()]["plan_id"])),
                               publisher=noop, checker=noop, planner=noop, cleaner=noop)
            self.assertEqual(calls, [("2026-11-04", b["id"])])

    def test_run_now_makes_the_plan_you_clicked_even_when_a_scheduled_plan_is_still_to_make(self):
        # 2026-11-05: Run now on the API security plan made the day's vetoed Game Server plan again, which was back to "still to make"
        with TempWorkspace() as ws:
            self.ws(ws)
            a, = self.assigned(ws, 1, "2026-11-05")
            own = monthly.add_manual(ws, "linkedin", "How API security works", "details")
            monthly.run_plan(ws, "linkedin", own["id"], None, today=date(2026, 11, 5))
            self.assertEqual(planner.load_plan(ws)["2026-11-05"]["plan_id"], own["id"])
            ws.save_queue([{"id": "p2", "date": "2026-11-05", "topic": own["title"], "platform": "linkedin", "plan_id": own["id"],
                            "status": "awaiting_approval"}])
            monthly.sync_all(ws, "linkedin")
            self.assertEqual(planner.load_plan(ws)["2026-11-05"]["plan_id"], a["id"])   # once yours is made, the scheduled one is next again

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
    def test_an_assigned_video_starts_from_a_guide_length(self):
        from postcrew import monthly
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"]["enabled"] = True
            ws.save_config(cfg)
            cid = monthly.category_for_item(ws, "youtube", "short")
            self.assertEqual(ws.config()["platforms"]["youtube"]["categories"][cid]["target_seconds"], 90)
            self.assertEqual(monthly.category_for_item(ws, "youtube", "long"), "assigned-long")
            self.assertEqual(ws.config()["platforms"]["youtube"]["categories"]["assigned-long"]["target_seconds"], 480)


class TrendPlanningTests(unittest.TestCase):
    """YouTube plans come from what works on YouTube; the calendar is filled at random; plans can be run by hand."""

    def video(self, i, views, likes, age, short=False):
        return {"id": f"vid{i:08d}"[:11], "title": f"Load balancer video {i}", "channel": "Chan", "views": views, "likes": likes, "age_days": age,
                "seconds": 45 if short else 600, "description": "0:00 Intro\\n1:00 Round robin\\n2:00 Health checks", "chapters": [], "tags": ["lb"]}

    def research(self):
        from postcrew import trends
        vids = [trends.with_rates(self.video(i, 50000 * (i + 1), 2500 * (i + 1), 20 + i * 10)) for i in range(5)]
        return {"topic": "Load balancers", "researched_at": "2026-11-03T00:00:00+00:00", "videos": vids, "metrics": trends.metrics(vids)}

    def yt_answer(self, research, n=6):
        ids = [v["id"] for v in research["videos"]]
        plans = []
        for i in range(n):
            p = plan(TITLES[i], i)
            p["trend"] = {"why": "views are climbing", "evidence": [ids[i % 5], "not-a-real-id"], "covers": ["round robin"], "gap": "no worked example"}
            plans.append(p)
        return {"plans": plans}

    def test_each_topic_gets_five_or_six_researched_plans_on_youtube_and_a_months_days_on_linkedin(self):
        from helpers import REAL_PER_TOPIC
        self.assertEqual(REAL_PER_TOPIC("youtube", "2026-11", ["a", "b", "c"]), 6)
        self.assertEqual(REAL_PER_TOPIC("linkedin", "2026-11", ["a", "b", "c"]), 10)       # 30 days over 3 topics
        self.assertEqual(REAL_PER_TOPIC("linkedin", "2026-12", ["a"]), 31)                  # one post a day is all it needs
        from unittest import mock
        res = self.research()
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"].update(enabled=True, topics=["Load balancers"])
            ws.save_config(cfg)
            with mock.patch.object(monthly, "per_topic", REAL_PER_TOPIC), mock.patch("postcrew.trends.niche_research", return_value=res):
                out = monthly.generate(ws, "youtube", "2026-11", llm=ScriptedLLM({"planner": [self.yt_answer(res)]}), today=TODAY)
            self.assertEqual(out["added"], 6)
            items = monthly.view(ws, "youtube", "2026-11", TODAY)["items"]
            r = items[0]["research"]
            self.assertEqual(r["why"], "views are climbing")
            self.assertEqual(len(r["videos"]), 1)                                            # the made-up id was dropped, the real one kept
            self.assertTrue(r["trend_score"] and r["label"] in ("hot", "steady", "niche") and r["engagement_pct"])
            self.assertIn("round robin", r["covers"])

    def test_the_calendar_is_filled_at_random_with_every_topic_taking_turns_and_nothing_overwritten(self):
        import random
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["topics"] = ["Breakers", "Retries"]
            ws.save_config(cfg)
            titles = TITLES[:10]
            monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(titles)]}), today=TODAY)
            first = monthly.view(ws, "linkedin", "2026-11", TODAY)["items"][0]
            monthly.assign(ws, "linkedin", first["id"], "2026-11-10", today=TODAY)                   # by hand, before
            out = monthly.auto_assign(ws, "linkedin", "2026-11", today=TODAY, rng=random.Random(1))
            v = monthly.view(ws, "linkedin", "2026-11", TODAY)
            self.assertGreater(out["assigned"], 0)
            self.assertNotIn("2026-11-10", out["days"])                                              # a day that already had a plan is left alone
            self.assertTrue(all(d >= "2026-11-03" for d in v["days"]))                              # never a day that is over
            self.assertEqual(v["days"]["2026-11-10"][0]["id"], first["id"])
            again = monthly.auto_assign(ws, "linkedin", "2026-11", today=TODAY, rng=random.Random(2))
            self.assertEqual(again["assigned"], 0 if v["counts"]["unassigned"] == 0 else again["assigned"])   # nothing placed twice

    def test_a_plan_can_be_run_by_hand_and_goes_first_today(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"].update(enabled=True, topics=["Breakers"])
            ws.save_config(cfg)
            monthly.generate(ws, "youtube", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:10])]}), today=TODAY)
            rows = monthly.unassigned(ws, "youtube")
            self.assertEqual(len(rows), 10)
            a, b = rows[0], rows[1]
            monthly.assign(ws, "youtube", a["id"], "2026-11-03", "short", today=TODAY)              # already waiting today
            info = monthly.run_plan(ws, "youtube", b["id"], "long", today=TODAY)
            self.assertEqual((info["date"], info["category"]), ("2026-11-03", "assigned-long"))
            self.assertEqual(planner.load_plan(ws, "youtube")["2026-11-03"]["plan_id"], b["id"])    # the crew makes the chosen plan, not the one waiting
            self.assertNotIn(b["id"], [r["id"] for r in monthly.unassigned(ws, "youtube")])

    def test_a_plan_you_choose_is_made_before_one_placed_at_random(self):
        import random
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["topics"] = ["Breakers"]
            ws.save_config(cfg)
            monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:10])]}), today=TODAY)
            monthly.auto_assign(ws, "linkedin", "2026-11", today=TODAY, rng=random.Random(3))
            v = monthly.view(ws, "linkedin", "2026-11", TODAY)
            day, auto_id = next(iter(v["days"].items()))[0], next(iter(v["days"].values()))[0]["id"]
            mine = next(i for i in v["items"] if i["status"] == "assigned" and i["assigned"]["date"] != day)   # every plan is on a day: move one here
            monthly.assign(ws, "linkedin", mine["id"], day, today=TODAY)
            self.assertEqual(monthly.view(ws, "linkedin", "2026-11", TODAY)["days"][day][0]["id"], mine["id"])   # first in line
            self.assertEqual(monthly.view(ws, "linkedin", "2026-11", TODAY)["days"][day][1]["id"], auto_id)


class TrendParsingTests(unittest.TestCase):
    def test_what_youtube_shows_is_read_into_numbers(self):
        from postcrew import trends
        self.assertEqual((trends.parse_views("3,255,515 views"), trends.parse_views("1.2M views"), trends.parse_views("No views"), trends.parse_views("hello")),
                         (3255515, 1200000, 0, None))
        self.assertEqual((trends.parse_age("2y ago"), trends.parse_age("6 months ago"), trends.parse_age("Streamed 3 weeks ago"), trends.parse_age("5 hours ago")),
                         (730, 180, 21, 0))
        self.assertEqual((trends.parse_duration("1:05:22"), trends.parse_duration("7:56")), (3922, 476))
        chapters = trends.parse_chapters("Intro\n0:00 Start\n1:30 Round robin\n4:10 Health checks\nthanks")
        self.assertEqual([c["title"] for c in chapters], ["Start", "Round robin", "Health checks"])
        self.assertEqual(trends.parse_chapters("0:00 only one"), [])

    def test_trend_and_engagement_come_from_views_per_day_and_likes(self):
        from postcrew import trends
        hot = [trends.with_rates({"id": f"v{i:010d}", "title": "t", "views": 400000, "likes": 20000, "age_days": 60, "seconds": 600}) for i in range(4)]
        m = trends.metrics(hot)
        self.assertEqual((m["label"], m["engagement_pct"]), ("hot", 5.0))
        self.assertGreaterEqual(m["trend_score"], 70)
        slow = [trends.with_rates({"id": f"w{i:010d}", "title": "t", "views": 900, "likes": 20, "age_days": 400, "seconds": 600}) for i in range(4)]
        self.assertEqual(trends.metrics(slow)["label"], "niche")
        self.assertEqual(trends.metrics([]), {})

    def test_a_search_page_and_a_watch_page_are_parsed_and_a_dead_network_gives_nothing(self):
        import json
        from postcrew import trends
        data = {"contents": [{"videoRenderer": {"videoId": "abcdefghijk", "title": {"runs": [{"text": "Load balancers"}]}, "ownerText": {"runs": [{"text": "Chan"}]},
                                                 "viewCountText": {"simpleText": "120,000 views"}, "publishedTimeText": {"simpleText": "3 weeks ago"},
                                                 "lengthText": {"simpleText": "12:30"}}}]}
        page = "<script>var ytInitialData = " + json.dumps(data) + ";</script>"
        hits = trends.parse_search(page)
        self.assertEqual((hits[0]["id"], hits[0]["views"], hits[0]["age_days"], hits[0]["seconds"]), ("abcdefghijk", 120000, 21, 750))
        watch = '"viewCount":"120000","likeCount":"4800","publishDate":"2026-10-12T00:00:00-07:00","shortDescription":"0:00 Intro\\n1:00 A\\n2:00 B","keywords":["lb","nginx"]'
        info = trends.parse_watch(watch)
        self.assertEqual((info["views"], info["likes"], info["tags"]), (120000, 4800, ["lb", "nginx"]))
        self.assertEqual(len(info["chapters"]), 3)
        def dead(url, timeout=25):
            raise OSError("no network")
        out = trends.niche_research("anything", fetcher=dead)
        self.assertEqual((out["videos"], out["metrics"]), ([], {}))
        self.assertIn("did not answer", out["error"])


class TrendingStudyTests(unittest.TestCase):
    def test_the_researcher_studies_the_trending_videos_and_the_writer_is_told_what_they_miss(self):
        from unittest import mock
        from postcrew import trends
        from postcrew.agents.base import RunContext
        from postcrew.agents.research import ResearchAgent
        from postcrew.agents.writer import research_block
        from postcrew.runlog import RunLog
        vids = [trends.with_rates({"id": f"vid{i:08d}", "title": f"Load balancer {i}", "channel": "Chan", "views": 90000 * (i + 1), "likes": 3000 * (i + 1),
                                   "age_days": 30 + i, "seconds": 600, "description": "0:00 Intro\n1:00 Round robin\n3:00 Health checks", "chapters":
                                   [{"at": 0, "title": "Intro"}, {"at": 60, "title": "Round robin"}, {"at": 180, "title": "Health checks"}], "tags": ["lb"]})
                for i in range(3)]
        research = {"topic": "Load balancers", "videos": vids, "metrics": trends.metrics(vids)}
        answer = {"videos": [{"id": vids[0]["id"], "opening": "a site that crashed", "structure": ["intro", "round robin", "health checks"],
                              "covers": ["round robin"], "works": "clear story", "weak": "no failure case"},
                             {"id": "not-listed", "opening": "x", "structure": [], "covers": [], "works": "", "weak": ""}],
                  "common_topics": ["round robin", "health checks"], "gaps": ["no worked example"], "outline": ["problem", "idea", "mistake"], "title_patterns": ["a number"]}
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"].update(enabled=True)
            ws.save_config(cfg)
            cat = monthly.category_for_item(ws, "youtube", "short")
            ycfg = platforms_view(ws, "youtube")
            run = RunLog(ws.root / "runs" / "t", "t", meta={})
            ctx = RunContext(ws=ws, cfg=ycfg, day=TODAY, category=cat, run=run, llm=ScriptedLLM({"research": [answer]}), platform="youtube")
            ctx.outputs["topic"] = {"topic": "Load balancers", "angle": "how they pick a server"}
            with mock.patch("postcrew.trends.niche_research", return_value=research):
                t = ResearchAgent()._trending(ctx, ctx.outputs["topic"])
        self.assertEqual([v["id"] for v in t["videos"]], [vids[0]["id"]])                      # an id the model made up is dropped
        self.assertEqual(t["videos"][0]["views"], 90000)                                       # the numbers are YouTube's, not the model's
        self.assertEqual(t["gaps"], ["no worked example"])
        text = research_block({"verified": [], "trending": t})
        self.assertIn("TRENDING VIDEOS ON THIS TOPIC", text)
        self.assertIn("no worked example", text)
        self.assertIn("opens with a site that crashed", text)


def platforms_view(ws, platform):
    from postcrew import platforms
    return platforms.view(ws.config(), platform)


class SpreadTests(unittest.TestCase):
    def test_fewer_plans_than_days_land_on_random_days_across_the_whole_month(self):
        import random
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["topics"] = ["Breakers"]
            ws.save_config(cfg)
            monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:10])]}), today=TODAY)
            days = monthly.auto_assign(ws, "linkedin", "2026-11", today=TODAY, rng=random.Random(5))["days"]
            self.assertEqual(len(days), 10)
            self.assertEqual(days, sorted(set(days)))                                    # one plan a day
            self.assertNotEqual(days, [f"2026-11-{d:02d}" for d in range(3, 13)])        # not simply the first ten days
            self.assertGreater(max(days), "2026-11-20")                                  # the plans reach into the end of the month


class RegenerateTests(unittest.TestCase):
    """The Generate plan button: clear what is not made yet, write new plans, put them on the month's days."""

    def prepare(self, ws):
        cfg = ws.config()
        cfg["topics"] = ["Breakers"]
        ws.save_config(cfg)
        monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:10])]}), today=TODAY)

    def test_old_plans_are_cleared_new_ones_written_and_placed_on_the_month(self):
        with TempWorkspace() as ws:
            self.prepare(ws)
            old = {i["title"] for i in monthly.view(ws, "linkedin", "2026-11", TODAY)["items"]}
            monthly.auto_assign(ws, "linkedin", "2026-11", today=TODAY)
            self.assertTrue(monthly.view(ws, "linkedin", "2026-11", TODAY)["days"])
            fresh = ["Alerting on breaker trips", "Breakers and queues", "Chaos testing breakers", "Breakers on the edge", "Shadow traffic for breakers",
                     "Breakers in batch jobs", "Per-tenant breakers", "Breakers for databases", "Sizing breaker windows", "Breakers in gRPC"]
            out = monthly.regenerate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(fresh)]}), today=TODAY)
            self.assertEqual((out["cleared"], out["added"]), (10, 10))
            v = monthly.view(ws, "linkedin", "2026-11", TODAY)
            self.assertEqual({i["title"] for i in v["items"]}, set(fresh))                  # none of the old plans is left
            self.assertFalse(old & {i["title"] for i in v["items"]})
            self.assertEqual(v["counts"]["assigned"], 10)                                    # and the new ones are on days of the month
            self.assertTrue(all(d >= "2026-11-03" for d in v["days"]))
            self.assertEqual(len(set(v["days"])), 10)

    def test_a_plan_whose_post_is_in_the_queue_is_kept_with_its_day(self):
        with TempWorkspace() as ws:
            self.prepare(ws)
            first = monthly.view(ws, "linkedin", "2026-11", TODAY)["items"][0]
            monthly.assign(ws, "linkedin", first["id"], "2026-11-10", today=TODAY)
            ws.save_queue([{"id": "2026-11-10-briefed-x", "platform": "linkedin", "plan_id": first["id"], "topic": first["title"], "status": "queued",
                            "date": "2026-11-10", "text": "t"}])
            gone = monthly.clear_plans(ws, "linkedin")
            self.assertEqual((gone["cleared"], gone["kept"]), (9, 1))
            v = monthly.view(ws, "linkedin", "2026-11", TODAY)
            self.assertEqual([i["id"] for i in v["items"]], [first["id"]])
            self.assertIn("2026-11-10", v["days"])                                           # its day stays

    def test_when_no_plan_can_be_written_the_old_plans_come_back(self):
        from postcrew.agents import planner as pl
        from postcrew.llm import LLMError
        with TempWorkspace() as ws:
            self.prepare(ws)
            monthly.auto_assign(ws, "linkedin", "2026-11", today=TODAY)
            before = monthly.view(ws, "linkedin", "2026-11", TODAY)
            llm = ScriptedLLM({"planner": [LLMError("the model is down", kind="failed")] * 6})
            with self.assertRaises(ValueError) as caught:
                monthly.regenerate(ws, "linkedin", "2026-11", llm=llm, today=TODAY)
            self.assertIn("previous plans were kept", str(caught.exception))
            after = monthly.view(ws, "linkedin", "2026-11", TODAY)
            self.assertEqual(({i["id"] for i in after["items"]}, set(after["days"])), ({i["id"] for i in before["items"]}, set(before["days"])))
            self.assertEqual(set(pl.load_plan(ws)), set(before["days"]))                    # the day plans are back too


class PlanJobTests(unittest.TestCase):
    """Generate plan is a background job that survives a dropped connection and a restart of the Studio."""

    def studio(self, ws):
        from postcrew.studio.server import Studio
        return Studio(ws)

    def test_the_job_returns_at_once_reports_progress_and_the_deploy_waits_for_it(self):
        from unittest import mock
        from helpers import wait_plan_job
        gate = __import__("threading").Event()

        class SlowLLM(ScriptedLLM):
            def call(self, *a, **k):
                gate.wait(5)
                return super().call(*a, **k)
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["topics"] = ["Breakers"]
            ws.save_config(cfg)
            st = self.studio(ws)
            with mock.patch("postcrew.llm.make_backend", return_value=SlowLLM({"planner": [answer(TITLES[:10])]})):
                started = st.plan_generate({"platform": "linkedin"})
                self.assertEqual(started["state"], "running")
                self.assertTrue(st.planning)                                                    # the lab's deploy hook sees this and waits
                self.assertTrue(st.overview("linkedin")["planning"])
                import time
                for _ in range(100):                                                            # the thread has just started: wait for its first message
                    if st.plan_job("linkedin")["message"] != "Starting…":
                        break
                    time.sleep(0.02)
                self.assertIn("Topic 1 of 1", st.plan_job("linkedin")["message"])
                with self.assertRaises(ValueError):                                             # a second press while it runs is refused
                    st.plan_generate({"platform": "linkedin"})
                self.assertEqual(st.plan("linkedin")["job"]["state"], "running")
                gate.set()
                job = wait_plan_job(lambda: st.plan_job("linkedin"))
            self.assertEqual((job["state"], job["result"]["added"]), ("done", 10))
            self.assertFalse(st.planning)
            self.assertEqual(ws.state("plan-job", {}), {})                                      # the restart marker is gone when it ends

    def test_a_job_that_a_restart_interrupted_is_carried_on(self):
        from unittest import mock
        from helpers import wait_plan_job
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["topics"] = ["Breakers"]
            ws.save_config(cfg)
            ws.save_state("plan-job", {"linkedin": {"month": "2026-11", "started_at": "2026-11-02T06:00:00+00:00"}})   # left behind by a killed server
            st = self.studio(ws)
            with mock.patch("postcrew.llm.make_backend", return_value=ScriptedLLM({"planner": [answer(TITLES[:10])]})):
                st.resume_plan_jobs()
                job = wait_plan_job(lambda: st.plan_job("linkedin"))
            self.assertEqual((job["state"], job["resumed"], job["result"]["added"]), ("done", True, 10))
            self.assertEqual(ws.state("plan-job", {}), {})


class NicheAndTopicsTests(unittest.TestCase):
    """The YouTube niche is hands-on builds and solved problems; plans follow the topics that are in Settings now."""

    def test_interview_advice_and_concept_lists_are_refused_but_solving_and_building_are_planned(self):
        bad = ["How to Answer Any System Design Interview: A 5-Step Framework", "Vector Databases Explained: What Interviewers Expect You to Know",
               "System Design Interview Tips for Beginners", "Backend Developer Roadmap", "10 concepts every engineer should know",
               "Cracking the Coding Interview: how to prepare"]
        good = ["How to Solve Two Sum: Brute Force to Hash Map, in Python", "Design a Chatbot: Build the Whole Pipeline Step by Step",
                "Build Single Sign-On with OAuth 2: the Login Flow by Hand", "LRU Cache: Solve the Interview Problem in Python"]
        for t in bad:
            self.assertTrue(monthly.MonthPlanner.problems(plan(t), [], youtube=True), t)
            self.assertFalse([p for p in monthly.MonthPlanner.problems(plan(t), [], youtube=False) if "interviews" in p])   # LinkedIn is not restricted
        for t in good:
            self.assertEqual(monthly.MonthPlanner.problems(plan(t), [], youtube=True), [], t)

    def test_research_searches_build_and_tutorial_videos_not_interview_ones(self):
        from postcrew import trends
        self.assertNotIn("interview", " ".join(trends.SUFFIXES))
        self.assertTrue(any("build" in s for s in trends.SUFFIXES))

    def test_an_algorithm_video_must_solve_on_screen_but_an_explainer_needs_no_code(self):
        from postcrew.checks import storyboard_problems
        spec = {"format": "long", "wps": 2.5, "artist": True, "renderer": "remotion"}
        algo, explain = {"id": "leetcode", "label": "Solve Algorithmic Problems"}, {"id": "concepts", "label": "Explain Concepts"}
        talk = [{"layout": "diagram", "part": "idea", "nodes": ["A", "B"], "narration": "a b"}] * 6
        self.assertTrue(any("solves nothing" in p for p in storyboard_problems(talk, spec, algo)))
        built = talk[:5] + [{"layout": "trace", "part": "example", "cells": ["1"], "narration": "x"}]
        self.assertFalse(any("solves nothing" in p for p in storyboard_problems(built, spec, algo)))
        self.assertFalse(any("solves nothing" in p for p in storyboard_problems(talk, spec, explain)))   # an explainer is drawn, not coded
        self.assertFalse(any("solves nothing" in p for p in storyboard_problems(talk, dict(spec, artist=False), algo)))

    def test_plans_of_topics_removed_from_settings_are_dropped_with_their_days(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["topics"] = ["Breakers", "Retries"]
            ws.save_config(cfg)
            from unittest import mock
            with mock.patch.object(monthly, "per_topic", lambda p, m, t, d=1: 5):
                monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:5]), answer(TITLES[5:10])]}), today=TODAY)
            monthly.auto_assign(ws, "linkedin", "2026-11", today=TODAY)
            before = monthly.view(ws, "linkedin", "2026-11", TODAY)
            self.assertEqual({i["topic"] for i in before["items"]}, {"Breakers", "Retries"})
            cfg = ws.config()
            cfg["topics"] = ["Retries"]                                                       # the owner changes the topics in Settings
            ws.save_config(cfg)
            self.assertEqual(monthly.prune_stale_topics(ws, "linkedin"), 5)
            after = monthly.view(ws, "linkedin", "2026-11", TODAY)
            self.assertEqual({i["topic"] for i in after["items"]}, {"Retries"})
            self.assertTrue(set(after["days"]) < set(before["days"]) and len(after["days"]) == 5)   # the old topic's days left the calendar too
            from postcrew.agents import planner as pl
            self.assertEqual(set(pl.load_plan(ws)), set(after["days"]))

    def test_a_removed_topic_whose_post_is_already_written_is_kept(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["topics"] = ["Breakers"]
            ws.save_config(cfg)
            monthly.generate(ws, "linkedin", "2026-11", llm=ScriptedLLM({"planner": [answer(TITLES[:5])]}), today=TODAY)
            first = monthly.view(ws, "linkedin", "2026-11", TODAY)["items"][0]
            monthly.assign(ws, "linkedin", first["id"], "2026-11-10", today=TODAY)
            ws.save_queue([{"id": "x", "platform": "linkedin", "plan_id": first["id"], "topic": first["title"], "status": "queued", "date": "2026-11-10", "text": "t"}])
            cfg = ws.config()
            cfg["topics"] = ["Something else"]
            ws.save_config(cfg)
            self.assertEqual(monthly.prune_stale_topics(ws, "linkedin"), 4)
            self.assertEqual([i["id"] for i in monthly.view(ws, "linkedin", "2026-11", TODAY)["items"]], [first["id"]])

    def test_pruning_an_unknown_app_does_nothing_instead_of_failing(self):
        with TempWorkspace() as ws:
            self.assertEqual(monthly.prune_stale_topics(ws, "myspace"), 0)
            monthly.sync_all(ws, "myspace")                                                    # a run for an unknown app is refused later, not here


RETRY_TITLES = ["Jitter that saves databases", "Exponential backoff math", "Retry budgets per client", "Idempotent writes first",
                "Thundering herds at dawn", "Client token buckets", "Deadline propagation", "Hedged requests", "Poison messages",
                "Queue redelivery limits"]


class TwoADayTests(unittest.TestCase):
    """Two videos a day: a run at each of schedule.generate_times, two plans placed on each day (on two topics)."""

    def setUp(self):
        self.tmp = TempWorkspace()
        self.ws = self.tmp.__enter__()
        cfg = self.ws.config()
        cfg["topics"] = ["Circuit breaker pattern", "Retry storms"]
        cfg["schedule"].update(frequency="dates", days={}, generate_times=["10:00", "17:00"])
        self.ws.save_config(cfg)

    def tearDown(self):
        self.tmp.__exit__(None, None, None)

    def test_plans_fill_two_slots_a_day_on_different_topics(self):
        import random
        ws = self.ws
        llm = ScriptedLLM({"planner": [answer(TITLES[:10]), answer(RETRY_TITLES)]})
        monthly.generate(ws, "linkedin", "2026-11", llm=llm, today=TODAY)
        out = monthly.auto_assign(ws, "linkedin", "2026-11", today=date(2026, 11, 25), rng=random.Random(1))
        self.assertEqual(out["assigned"], 12)   # 25th to 30th: six days, two each
        days = monthly.view(ws, "linkedin", "2026-11", TODAY)["days"]
        for d in ("2026-11-25", "2026-11-30"):
            self.assertEqual(len(days[d]), 2)
            self.assertEqual(len({x["topic"] for x in days[d]}), 2)

    def test_the_scheduler_makes_one_video_at_each_time(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        import random
        ws = self.ws
        llm = ScriptedLLM({"planner": [answer(TITLES[:10]), answer(RETRY_TITLES)]})
        monthly.generate(ws, "linkedin", "2026-11", llm=llm, today=TODAY)
        monthly.auto_assign(ws, "linkedin", "2026-11", today=date(2026, 11, 29), rng=random.Random(1))
        cfg = ws.config()
        cfg["schedule"]["lead_days"] = 0
        ws.save_config(cfg)
        tz = ZoneInfo(cfg["schedule"]["timezone"])
        made, noop = [], (lambda *a, **k: None)

        def runner(w, d):   # stands in for the crew: the day's current plan is made (written into the Queue)
            entry = planner.load_plan(w)[d.isoformat()]
            made.append(entry["plan_id"])
            w.save_queue(w.queue() + [{"id": f"p{len(made)}", "date": d.isoformat(), "topic": entry["topic"], "platform": "linkedin",
                                       "plan_id": entry["plan_id"], "status": "awaiting_approval"}])
            monthly.sync_all(w, "linkedin")
        for hh, mm in ((9, 0), (10, 1), (10, 30), (16, 59), (17, 1), (18, 0), (22, 0)):
            scheduler.tick(ws, datetime(2026, 11, 29, hh, mm, tzinfo=tz), runner=runner, publisher=noop, checker=noop, planner=noop, cleaner=noop)
        self.assertEqual(len(made), 2)
        self.assertEqual(len(set(made)), 2)

    def test_youtube_writes_enough_plans_for_two_a_day(self):
        from helpers import REAL_PER_TOPIC
        self.assertEqual(REAL_PER_TOPIC("youtube", "2026-11", ["a"] * 6), 6)
        self.assertEqual(REAL_PER_TOPIC("youtube", "2026-11", ["a"] * 6, 2), 11)   # 60 runs over 6 topics, plus one each to run by hand
