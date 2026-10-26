"""Week Planner: plans the rest of the week, never repeats, and the Topic Scout follows the plan."""
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

MONDAY = date(2026, 10, 12)          # this week = 2026-10-12 .. 2026-10-18


def day_answer(d, topic, queries=()):
    return {"date": d, "topic": topic, "angle": f"what to know about {topic}", "search_queries": list(queries)}


class PlannerTests(unittest.TestCase):
    def test_plans_the_rest_of_this_week_and_leaves_fresh_news_for_the_day_before(self):
        with TempWorkspace() as ws:
            ws.add_history({"date": "2026-10-05", "topic": "Quick Sort in Java", "text": "Quick Sort in 12 lines"})
            dates = ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17"]
            topics = ["Git worktrees", "OAuth PKCE flow", "Python walrus operator", "Docker layer caching"]
            llm = ScriptedLLM({"planner": [{"days": [day_answer(d, t, ["q"]) for d, t in zip(dates, topics)]}]})
            out = planner.plan_week(ws, MONDAY, llm=llm)
            plan = planner.load_plan(ws)
            self.assertEqual(sorted(plan), dates + ["2026-10-18"])          # Tue-Sun of this week, nothing later
            self.assertNotIn("2026-10-13", plan)                           # Tuesday ai-news: plan_ahead false
            self.assertNotIn("2026-10-12", plan)                           # today's post is already being written
            self.assertEqual(plan["2026-10-18"]["topic"], "Week in review 2026-10-18")
            self.assertEqual(plan["2026-10-16"]["topic"], "Python walrus operator")
            self.assertEqual(len(llm.calls), 1)
            self.assertTrue(all("error" not in e for e in out.values()))
            self.assertEqual(ws.state("notifications")["items"][-1]["action"]["tab"], "plan")
            self.assertEqual(planner.plan_week(ws, MONDAY, llm=llm), {})  # nothing left to plan
            self.assertEqual(planner.days_left(date(2026, 10, 18)), [])    # Sunday: the week is over

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

    def test_owner_ideas_and_focus_reach_the_planner_and_used_ideas_are_left_out(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["categories"]["build-guide"]["ideas"] = ["Local RAG with Ollama", "GitHub Actions CI pipeline"]
            cfg["planning"]["focus"] = "Keep every example in Python"
            ws.save_config(cfg)
            ws.add_history({"date": "2026-10-01", "topic": "Build a local RAG over your docs with Ollama"})
            self.assertEqual([x["used_on"] for x in planner.idea_status(ws)["build-guide"]], ["2026-10-01", None])
            llm = ScriptedLLM({"planner": [{"days": [day_answer("2026-10-21", "Build a GitHub Actions CI pipeline")]}]})
            planner.PlannerAgent().plan(ws, [date(2026, 10, 21)], llm=llm)
            prompt = llm.calls[0]["prompt"]
            self.assertIn("THE OWNER'S TOPIC IDEAS for this category, not used yet: ['GitHub Actions CI pipeline']", prompt)
            self.assertIn("Keep every example in Python", prompt)
            self.assertEqual(planner.idea_status(ws)["build-guide"][1]["used_on"], "2026-10-21")

    def test_replan_replaces_planner_topics_keeps_yours_and_rejects_nothing(self):
        with TempWorkspace() as ws:
            planner.set_entry(ws, "2026-10-21", {"category": "build-guide", "topic": "Feature flags done right",
                                                 "angle": "a", "search_queries": [], "source": "planner"})
            planner.set_entry(ws, "2026-10-22", {"category": "tool-spotlight", "topic": "Hurl API tests",
                                                 "angle": "a", "search_queries": ["hurl"], "source": "manual"})
            llm = ScriptedLLM({"planner": [{"days": [day_answer("2026-10-21", "Docker multi-stage builds")]}]})
            planner.PlannerAgent().plan(ws, [date(2026, 10, 21), date(2026, 10, 22)], llm=llm, replan=True)
            plan = planner.load_plan(ws)
            self.assertEqual((plan["2026-10-21"]["topic"], plan["2026-10-21"]["rejected"]), ("Docker multi-stage builds", []))
            self.assertEqual(plan["2026-10-22"]["topic"], "Hurl API tests")
            self.assertIn("Plan these 1 day(s)", llm.calls[0]["prompt"])           # your day is only listed as taken
            self.assertNotIn("rejected these", llm.calls[0]["prompt"])

    def test_bad_ideas_are_refused(self):
        from postcrew.workspace import validate_config
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["categories"]["dev-tip"]["ideas"] = ["ok idea", "x"]
            self.assertTrue(any("ideas" in e for e in validate_config(cfg)))

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
                                                 "angle": "when := helps", "search_queries": ["python walrus"],
                                                 "source": "planner"})
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


class PlannerBriefTests(unittest.TestCase):
    def test_planner_writes_a_brief_for_each_day(self):
        from postcrew import brief
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["schedule"]["days"]["wed"] = "briefed"
            ws.save_config(cfg)
            day = {"date": "2026-10-21", "topic": "Why agents need short-lived tokens", "angle": "token exchange",
                   "search_queries": ["token exchange rfc 8693"],
                   "context": "Agents hold broad tokens.", "example": "A refund agent with one admin token.",
                   "example_kind": "incident", "references": [], "takeaway": "Exchange tokens per task.",
                   "pattern": "before-after", "question": "How do you issue agent credentials?", "visual": "system-flow",
                   "systems": [{"id": "agent", "label": "Agent", "kind": "agent", "note": "acts"},
                               {"id": "api", "label": "API", "kind": "api-gateway", "note": "checks"}],
                   "flow": [{"from": "agent", "to": "api", "label": "POST refund", "kind": "request",
                             "payload": "Bearer admin", "caption": "The agent calls the API", "scene": "Before"},
                            {"from": "api", "to": "agent", "label": "Refunded", "kind": "response",
                             "payload": "200 OK", "caption": "Everything is refunded", "scene": "Before"}]}
            llm = ScriptedLLM({"planner": [{"days": [day]}]})
            out = planner.PlannerAgent().plan(ws, [date(2026, 10, 21)], llm=llm)
            b = out["2026-10-21"]["brief"]
            self.assertEqual(b["pattern"], "before-after")
            self.assertEqual(b["example_kind"], "scenario")   # an incident without a source is only a scenario
            self.assertEqual(b["visual"]["type"], "system-flow")
            self.assertEqual(len(b["visual"]["flow"]), 2)
            self.assertIn("example", b["generated"])
            self.assertEqual(planner.load_plan(ws)["2026-10-21"]["brief"], b)
            self.assertIn("ABOUT THIS TYPE", llm.calls[0]["prompt"]) if ws.config()["categories"]["briefed"].get("context") else None
