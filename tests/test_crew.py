import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from helpers import (DEV_TIP, GOOD_TEXT, PAGE_URL, SATURDAY, TUESDAY, FakeLinkedIn, ScriptedLLM, TempWorkspace,
                     fake_fetch, poster_spec, research, review, topic, writer)
from postcrew.agents import credentials as cred_mod
from postcrew.agents.formatter import format_post
from postcrew.agents.publisher import publish_due
from postcrew.crew import run_crew
from postcrew.llm import LLMError

CLAUDE_OK = {"state": "ok", "message": "logged in"}


def events(ws, run_id):
    return [json.loads(l) for l in (ws.runs_dir / run_id / "events.jsonl").read_text().splitlines()]


def status(ws, run_id):
    return json.loads((ws.runs_dir / run_id / "status.json").read_text())


@mock.patch.object(cred_mod, "check_claude", return_value=CLAUDE_OK)
class CrewTests(unittest.TestCase):
    def script(self, **over):
        s = {"topic": [topic()], "research": [research()], "writer": [writer()], "media": [poster_spec()],
             "editor": [review()], "supervisor": [{"action": "retry", "target": "writer", "instructions": ["fix it"],
                                                   "reason": "test"}]}
        s.update(over)
        return s

    def test_happy_path_queues_a_verified_post_with_poster(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script())
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            st = status(ws, res["run_id"])
            self.assertEqual(st["state"], "succeeded")
            self.assertEqual({s: v["state"] for s, v in st["steps"].items()},
                             {"credentials": "passed", "topic": "passed", "research": "passed", "writer": "passed",
                              "media": "passed", "editor": "passed", "formatter": "passed", "publisher": "passed"})
            q = ws.queue()
            self.assertEqual(len(q), 1)
            self.assertEqual(q[0]["status"], "queued")
            self.assertEqual(q[0]["first_comment"], PAGE_URL)
            self.assertTrue((ws.root / q[0]["media"]).stat().st_size > 10_000)  # real PNG rendered
            self.assertEqual(llm.agents_called().count("editor"), 3)            # reviewed 3 times
            kinds = [(e["step"], e["kind"]) for e in events(ws, res["run_id"])]
            self.assertIn(("editor", "passed"), kinds)
            self.assertIn(("run", "finished"), kinds)
            self.assertGreater(st["cost_usd"], 0)

    def test_research_with_a_fake_quote_is_rejected_then_fixed(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(
                research=[research(quote="Acme Model 2 is free forever for everyone."), research()],
                supervisor=[{"action": "retry", "target": "research", "instructions": ["quote the pricing sentence exactly"],
                             "reason": "quote not on page"}]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            st = status(ws, res["run_id"])
            self.assertEqual(st["steps"]["research"]["attempts"], 2)
            self.assertEqual(st["interventions"], 1)
            retry_prompt = [c for c in llm.calls if c["agent"] == "research"][-1]["prompt"]
            self.assertIn("quote the pricing sentence exactly", retry_prompt)

    def test_unsourced_number_is_rejected_and_editor_can_rewind_to_research(self, _):
        bad = GOOD_TEXT.replace("Start with one", "Teams report 73% savings. Start with one")
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(
                writer=[writer(bad), writer()],
                editor=[review(55, ["unsupported_claim"], owner="research")] * 3 + [review()],
                supervisor=[{"action": "retry", "target": "writer", "instructions": ["remove 73%"], "reason": "unsourced"},
                            {"action": "rewind", "target": "research", "instructions": ["verify the claims"],
                             "reason": "editor flagged unsupported claim"}]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            decisions = [e["data"] for e in events(ws, res["run_id"]) if e["kind"] == "decision"]
            self.assertEqual(decisions[0]["target"], "writer")
            self.assertEqual(decisions[1]["action"], "rewind")
            self.assertEqual(decisions[1]["target"], "research")
            st = status(ws, res["run_id"])
            self.assertEqual(st["steps"]["research"]["attempts"], 2)

    def test_supervisor_unavailable_falls_back_to_editor_fix_owner(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(editor=[review(60, owner="media", fixes=["shorter poster title"])] * 3 + [review()],
                                          supervisor=[LLMError("down", kind="failed")]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            evs = events(ws, res["run_id"])
            self.assertTrue(any(e["kind"] == "fallback" for e in evs))
            dec = next(e["data"] for e in evs if e["kind"] == "decision")
            self.assertEqual((dec["action"], dec["target"]), ("rewind", "media"))

    def test_editor_rejection_is_never_answered_by_re_reviewing(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(editor=[review(60, owner="writer")] * 3 + [review()],
                                          supervisor=[{"action": "retry", "target": "editor", "instructions": ["again"],
                                                       "reason": "model chose a pointless retry"}]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            dec = next(e["data"] for e in events(ws, res["run_id"]) if e["kind"] == "decision")
            self.assertEqual((dec["action"], dec["target"]), ("rewind", "writer"))
            self.assertEqual(status(ws, res["run_id"])["steps"]["writer"]["attempts"], 2)

    def test_writer_revises_its_previous_draft_after_review(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(editor=[review(60, owner="writer", fixes=["shorten the hook"])] * 3 + [review()]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            second = [c for c in llm.calls if c["agent"] == "writer"][1]["prompt"]
            self.assertIn("<previous_draft>", second)
            self.assertIn("Acme Model 2 costs $0.10", second)

    def test_gives_up_after_max_attempts_and_notifies(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(writer=[writer("Too short.")]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertFalse(res["ok"])
            self.assertEqual(res["failed_step"], "writer")
            st = status(ws, res["run_id"])
            self.assertEqual(st["steps"]["writer"]["attempts"], 3)
            self.assertEqual(st["steps"]["publisher"]["state"], "blocked")
            self.assertEqual(ws.queue(), [])
            notes = ws.state("notifications")["items"]
            self.assertTrue(any("No post for" in n["title"] for n in notes))

    def test_budget_limit_stops_the_run(self, _):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["pipeline"]["max_run_budget_usd"] = 0.5
            ws.save_config(cfg)
            llm = ScriptedLLM(self.script(writer=[writer("Too short.")]), cost=0.3)
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertFalse(res["ok"])
            self.assertIn("budget", res["reason"])

    def test_fatal_error_aborts_without_retrying(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(topic=[LLMError("not logged in", kind="auth")]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertFalse(res["ok"])
            self.assertEqual(status(ws, res["run_id"])["steps"]["topic"]["attempts"], 1)

    def test_repeat_topic_is_rejected(self, _):
        with TempWorkspace() as ws:
            ws.add_history({"id": "x", "date": "2026-10-01", "category": "ai-news", "topic": "Acme Model 2 pricing",
                            "text": "old"})
            llm = ScriptedLLM(self.script(topic=[topic(), topic("Acme agents SDK quickstart")],
                                          supervisor=[{"action": "retry", "target": "topic", "instructions": ["new topic"],
                                                       "reason": "repeat"}]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            self.assertEqual(ws.queue()[0]["topic"], "Acme agents SDK quickstart")

    def test_category_without_research_skips_researcher(self, _):
        with TempWorkspace() as ws:
            spec = {"layout": "code", "title": "Default arguments are [[shared]]", "language": "python",
                    "code": "def add(item, items=None):\n    if items is None:\n        items = []\n    items.append(item)\n    return items",
                    "caption": "Use None, then create the list inside"}
            llm = ScriptedLLM(self.script(topic=[topic("Mutable default arguments in Python", [])],
                                          writer=[writer(DEV_TIP, "")], media=[spec]))
            res = run_crew(ws, SATURDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            self.assertEqual(status(ws, res["run_id"])["steps"]["research"]["state"], "skipped")
            self.assertNotIn("research", llm.agents_called())

    def test_poster_code_that_does_not_parse_is_rejected(self, _):
        with TempWorkspace() as ws:
            bad = {"layout": "code", "title": "Tip", "language": "python", "code": "def f(:\n    pass", "caption": "x"}
            good = dict(bad, code="def f(x):\n    return x * 2\n\nprint(f(2))\nprint(f(3))")
            llm = ScriptedLLM(self.script(topic=[topic("Mutable default arguments in Python", [])],
                                          writer=[writer(DEV_TIP, "")], media=[bad, good],
                                          supervisor=[{"action": "retry", "target": "media", "instructions": ["fix code"],
                                                       "reason": "syntax"}]))
            res = run_crew(ws, SATURDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            self.assertEqual(status(ws, res["run_id"])["steps"]["media"]["attempts"], 2)

    def test_dry_run_never_queues(self, _):
        with TempWorkspace() as ws:
            res = run_crew(ws, TUESDAY, llm=ScriptedLLM(self.script()), fetch=fake_fetch(), dry_run=True)
            self.assertTrue(res["ok"], res)
            self.assertEqual(ws.queue(), [])
            self.assertEqual(status(ws, res["run_id"])["steps"]["publisher"]["state"], "skipped")

    def test_invented_experience_is_rejected(self, _):
        with TempWorkspace() as ws:
            fake = GOOD_TEXT.replace("Start with one", "Last week I migrated our pipeline. Start with one")
            llm = ScriptedLLM(self.script(writer=[writer(fake)]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertFalse(res["ok"])
            self.assertTrue(any("personal experience" in p for p in res["problems"]), res["problems"])


@mock.patch.object(cred_mod, "check_claude", return_value=CLAUDE_OK)
class PublishTests(unittest.TestCase):
    def queue_one(self, ws, mode="auto_with_veto", dry=True):
        cfg = ws.config()
        cfg["publishing"].update(approval=mode, dry_run=dry)
        ws.save_config(cfg)
        llm = ScriptedLLM(CrewTests.script(CrewTests()))
        res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
        self.assertTrue(res["ok"], res)
        return ws.queue()[0]

    def test_dry_run_publish_sends_nothing(self, _):
        with TempWorkspace() as ws:
            p = self.queue_one(ws)
            FakeLinkedIn.posts = []
            res = publish_due(ws, now=datetime.fromisoformat(p["scheduled_at"]) + timedelta(minutes=1),
                              client_factory=FakeLinkedIn, log=lambda m: None)
            self.assertEqual(res[0]["status"], "dry_run")
            self.assertEqual(FakeLinkedIn.posts, [])

    def test_live_publish_waits_until_post_time_then_posts_once(self, _):
        with TempWorkspace() as ws:
            p = self.queue_one(ws, dry=False)
            ws.update_secrets(linkedin_client_id="abcdefgh12", linkedin_client_secret="s", linkedin_access_token="good",
                              linkedin_token_expires_at=(datetime.now(timezone.utc) + timedelta(days=50)).isoformat())
            FakeLinkedIn.posts = []
            at = datetime.fromisoformat(p["scheduled_at"])
            with mock.patch.object(cred_mod, "LinkedIn", FakeLinkedIn):
                self.assertEqual(publish_due(ws, now=at - timedelta(minutes=5), client_factory=FakeLinkedIn), [])
                res = publish_due(ws, now=at + timedelta(minutes=1), client_factory=FakeLinkedIn, log=lambda m: None)
            self.assertEqual(res[0]["status"], "published")
            self.assertEqual(len(FakeLinkedIn.posts), 1)
            self.assertEqual(FakeLinkedIn.posts[0]["media"], "urn:li:image:1")
            self.assertEqual(ws.queue(), [])
            self.assertEqual(ws.history()[0]["urn"], "urn:li:share:1")

    def test_manual_mode_waits_for_approval(self, _):
        with TempWorkspace() as ws:
            p = self.queue_one(ws, mode="manual")
            self.assertEqual(p["status"], "awaiting_approval")
            later = datetime.fromisoformat(p["scheduled_at"]) + timedelta(days=1)
            self.assertEqual(publish_due(ws, now=later), [])

    def test_vetoed_post_is_never_published(self, _):
        with TempWorkspace() as ws:
            p = self.queue_one(ws)
            ws.save_queue([dict(p, status="vetoed")])
            self.assertEqual(publish_due(ws, now=datetime.fromisoformat(p["scheduled_at"]) + timedelta(hours=1)), [])

    def test_invalid_token_blocks_publishing_and_keeps_post(self, _):
        with TempWorkspace() as ws:
            p = self.queue_one(ws, dry=False)
            ws.update_secrets(linkedin_access_token="bad")
            with mock.patch.object(cred_mod, "LinkedIn", FakeLinkedIn):
                res = publish_due(ws, now=datetime.fromisoformat(p["scheduled_at"]) + timedelta(minutes=1),
                                  client_factory=FakeLinkedIn, log=lambda m: None)
            self.assertEqual(res[0]["status"], "queued")
            self.assertIn("rejected", res[0]["error"])
            self.assertEqual(ws.queue()[0]["status"], "queued")


class FormatterTests(unittest.TestCase):
    def test_moves_links_and_cleans_hashtags(self):
        text, fc, moved = format_post("Hook line here​  \n\n\n\nRead https://x.com/a now.\n\n#AI #ai #LLM", "")
        self.assertEqual(text, "Hook line here\n\nRead  now.\n\n#AI #LLM")
        self.assertEqual(fc, "https://x.com/a")
        self.assertEqual(moved, ["https://x.com/a"])

    def test_keeps_existing_first_comment(self):
        _, fc, _ = format_post("Hook\n\nbody https://x.com/a", "https://y.com")
        self.assertEqual(fc, "https://y.com")


if __name__ == "__main__":
    unittest.main()
