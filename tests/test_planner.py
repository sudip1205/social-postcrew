"""Week Planner: plans next week ahead, never repeats, and the Topic Scout follows the plan."""
import json
import tempfile
import unittest
from datetime import date
from unittest import mock

from helpers import ScriptedLLM, TempWorkspace
from postcrew.__main__ import cmd_import
from postcrew.agents import planner
from postcrew.agents.base import RunContext
from postcrew.agents.topic import TopicAgent
from postcrew.runlog import RunLog

MONDAY = date(2026, 10, 12)          # next week = 2026-10-19 .. 2026-10-25


def day_answer(d, topic, queries=()):
    return {"date": d, "topic": topic, "angle": f"what to know about {topic}", "search_queries": list(queries)}


class PlannerTests(unittest.TestCase):
    def test_plans_next_week_and_leaves_fresh_news_for_the_day_before(self):
        with TempWorkspace() as ws:
            ws.add_history({"date": "2026-10-05", "topic": "Quick Sort in Java", "text": "Quick Sort in 12 lines"})
            # days 13-18 of this week are planned too (they had no plan); only the LLM categories are asked
            dates = ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-21", "2026-10-22",
                     "2026-10-23", "2026-10-24"]
            topics = ["Git worktrees", "OAuth PKCE flow", "Python walrus operator", "Docker layer caching",
                      "Kafka consumer groups", "Passkeys vs passwords", "SQL window functions", "Redis eviction"]
            llm = ScriptedLLM({"planner": [{"days": [day_answer(d, t, ["q"]) for d, t in zip(dates, topics)]}]})
            out = planner.plan_week(ws, MONDAY, llm=llm)
            plan = planner.load_plan(ws)
            self.assertNotIn("2026-10-20", plan)                       # Tuesday ai-news: plan_ahead false
            self.assertNotIn("2026-10-13", plan)
            self.assertEqual(plan["2026-10-19"]["source"], "auto")      # Monday algorithm, no LLM needed
            self.assertNotIn("Quick Sort", plan["2026-10-19"]["topic"])  # already posted
            self.assertEqual(plan["2026-10-25"]["topic"], "Week in review 2026-10-25")
            self.assertEqual(plan["2026-10-21"]["topic"], "Kafka consumer groups")
            self.assertEqual(len(llm.calls), 1)
            self.assertTrue(all("error" not in e for e in out.values()))
            self.assertEqual(ws.state("notifications")["items"][-1]["action"]["tab"], "plan")
            self.assertEqual(planner.plan_week(ws, MONDAY, llm=llm), {})  # nothing left to plan

    def test_repeats_are_sent_back_and_rejected_topics_never_return(self):
        with TempWorkspace() as ws:
            ws.add_history({"date": "2026-10-01", "topic": "Rate limiting with token buckets"})
            llm = ScriptedLLM({"planner": [{"days": [day_answer("2026-10-21", "Rate limiting with token buckets")]},
                                           {"days": [day_answer("2026-10-21", "Feature flags done right")]}]})
            out = planner.PlannerAgent().plan(ws, [date(2026, 10, 21)], llm=llm)
            self.assertEqual(out["2026-10-21"]["topic"], "Feature flags done right")
            self.assertIn("topic repeats", llm.calls[1]["prompt"])
            # "Suggest another": the current topic is rejected and the owner's hint is passed on
            llm = ScriptedLLM({"planner": [{"days": [day_answer("2026-10-21", "Feature flags done right")]},
                                           {"days": [day_answer("2026-10-21", "Docker multi-stage builds")]}]})
            planner.PlannerAgent().plan(ws, [date(2026, 10, 21)], llm=llm, hint="something about Docker", force=True)
            e = planner.load_plan(ws)["2026-10-21"]
            self.assertEqual((e["topic"], e["rejected"]), ("Docker multi-stage builds", ["Feature flags done right"]))
            self.assertIn("something about Docker", llm.calls[0]["prompt"])
            self.assertIn("rejected", llm.calls[1]["prompt"])

    def test_used_up_usage_limit_stops_at_once_with_the_reason(self):
        from postcrew.llm import LLMError
        with TempWorkspace() as ws:
            llm = ScriptedLLM({"planner": [LLMError("your Claude usage limit is used up: resets 3:40am", kind="limit")]})
            out = planner.PlannerAgent().plan(ws, [date(2026, 10, 21), date(2026, 10, 22)], llm=llm)
            self.assertEqual(len(llm.calls), 1)
            self.assertIn("usage limit", out["2026-10-21"]["error"])
            self.assertNotIn("2026-10-21", out["2026-10-21"]["error"])

    def test_recent_posts_show_their_opening_line(self):
        with TempWorkspace() as ws:
            ws.add_history({"date": "2026-10-01", "topic": "Cheap small models",
                            "text": "\nAnthropic's Haiku 5.5 costs a fraction of Sonnet.\nMore"})
            llm = ScriptedLLM({"planner": [{"days": [day_answer("2026-10-21", "Feature flags done right")]}]})
            planner.PlannerAgent().plan(ws, [date(2026, 10, 21)], llm=llm)
            self.assertIn('Cheap small models - "Anthropic\'s Haiku 5.5 costs a fraction of Sonnet."',
                          llm.calls[0]["prompt"])


class TopicFollowsPlanTests(unittest.TestCase):
    def ctx(self, ws, day, category, llm):
        run = RunLog(ws.runs_dir / "t", "t")
        return RunContext(ws=ws, cfg=ws.config(), day=day, category=category, run=run, llm=llm)

    def test_planned_topic_is_used_without_asking(self):
        with TempWorkspace() as ws:
            planner.set_entry(ws, "2026-10-17", {"category": "dev-tip", "topic": "Python walrus operator",
                                                 "angle": "when := helps", "search_queries": [], "source": "planner"})
            llm = ScriptedLLM({})
            ctx = self.ctx(ws, date(2026, 10, 17), "dev-tip", llm)
            out = TopicAgent().run(ctx, [])
            self.assertEqual((out["topic"], llm.calls), ("Python walrus operator", []))
            self.assertEqual(TopicAgent().validate(ctx, out), [])

    def test_manual_topic_keeps_its_words_and_gets_search_queries(self):
        with TempWorkspace() as ws:
            ws.add_history({"date": "2026-10-01", "topic": "OAuth PKCE explained"})
            planner.set_entry(ws, "2026-10-16", {"category": "security", "topic": "OAuth PKCE explained",
                                                 "angle": "", "search_queries": [], "source": "manual"})
            llm = ScriptedLLM({"topic": [{"topic": "Something else", "angle": "x", "why_now": "RFC 9700",
                                          "search_queries": ["PKCE RFC 7636"]}]})
            ctx = self.ctx(ws, date(2026, 10, 16), "security", llm)
            out = TopicAgent().run(ctx, [])
            self.assertEqual((out["topic"], out["search_queries"]), ("OAuth PKCE explained", ["PKCE RFC 7636"]))
            self.assertEqual(TopicAgent().validate(ctx, out), [])     # the owner chose it, even though it repeats

    def test_import_adds_history_once(self):
        with TempWorkspace() as ws, tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"posts": [{"id": "p1", "date": "2026-10-12", "topic": "Cheap small models", "text": "Hi"},
                                 {"date": "2026-10-13"}]}, f)
            f.close()
            with mock.patch("builtins.print"):
                cmd_import(ws, f.name)
                cmd_import(ws, f.name)
            self.assertEqual([p["topic"] for p in ws.history()], ["Cheap small models"])
            self.assertNotIn("2026-10-12", planner.taken_dates(ws))   # imported: blocks repeats, not the date
