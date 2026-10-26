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

    @unittest.skipUnless(__import__("shutil").which("ffmpeg"), "ffmpeg not installed")
    def test_animated_video_category_queues_the_video_and_keeps_the_poster(self, _):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["categories"]["ai-news"]["media"] = "video"
            ws.save_config(cfg)
            res = run_crew(ws, TUESDAY, llm=ScriptedLLM(self.script()), fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            post = ws.queue()[0]
            self.assertEqual(post["media_kind"], "video")
            self.assertTrue(post["media"].endswith(".mp4") and post["poster_image"].endswith(".png"))
            self.assertTrue((ws.root / post["media"]).stat().st_size > 10_000)

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
                editor=[review(55, ["unsupported_claim"], owner="research")] * 1 + [review()],
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

    def test_editor_fixes_go_straight_to_their_owner_word_for_word(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(editor=[review(60, owner="media", fixes=["shorter poster title"])] * 1 + [review()],
                                          supervisor=[LLMError("down", kind="failed")]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            evs = events(ws, res["run_id"])
            self.assertNotIn("supervisor", llm.agents_called())   # nobody re-words the Editor's fixes
            media2 = [c for c in llm.calls if c["agent"] == "media"][1]["prompt"]
            self.assertIn("apply each one exactly as written", media2)
            self.assertIn("- shorter poster title", media2)
            dec = next(e["data"] for e in evs if e["kind"] == "decision")
            self.assertEqual((dec["action"], dec["target"]), ("rewind", "media"))

    def test_a_failing_review_sends_the_draft_back_without_the_other_reads(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(editor=[review(60, owner="writer"), review(), review(), review()],
                                          supervisor=[{"action": "rewind", "target": "writer", "instructions": ["fix"],
                                                       "reason": "weak"}]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            # round one: the first read failed, so 1 call, not 3; round two: all 3 reads passed
            self.assertEqual(llm.agents_called().count("editor"), 1 + 3)

    def test_runs_count_their_tokens(self, _):
        with TempWorkspace() as ws:
            from postcrew.runlog import RunLog
            run = RunLog(ws.runs_dir / "t", "t", meta={})
            run.add_tokens("writer", {"in": 100, "cached": 50, "out": 10})
            run.add_tokens("editor", {"in": 20, "cached": 0, "out": 5})
            run.add_tokens("editor", {"in": 0, "cached": 0, "out": 0})
            st = json.loads((ws.runs_dir / "t" / "status.json").read_text())
            self.assertEqual(st["tokens"], {"in": 120, "cached": 50, "out": 15})
            self.assertEqual(st["steps"]["editor"]["tokens"], {"in": 20, "cached": 0, "out": 5})

    def test_editor_rejection_is_never_answered_by_re_reviewing(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(editor=[review(60, owner="writer")] * 1 + [review()],
                                          supervisor=[{"action": "retry", "target": "editor", "instructions": ["again"],
                                                       "reason": "model chose a pointless retry"}]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            dec = next(e["data"] for e in events(ws, res["run_id"]) if e["kind"] == "decision")
            self.assertEqual((dec["action"], dec["target"]), ("rewind", "writer"))
            self.assertEqual(status(ws, res["run_id"])["steps"]["writer"]["attempts"], 2)

    def test_writer_revises_its_previous_draft_after_review(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(editor=[review(60, owner="writer", fixes=["shorten the hook"])] * 1 + [review()]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch(), dry_run=True)
            self.assertTrue(res["ok"], res)
            second = [c for c in llm.calls if c["agent"] == "writer"][1]["prompt"]
            self.assertIn("<previous_draft>", second)
            self.assertIn("Acme Model 2 costs $0.10", second)

    def test_sent_back_work_gets_the_reasons_and_the_crew_remembers_them(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(
                editor=[review(60, owner="writer", fixes=["shorten the hook"])] * 1 + [review()],
                supervisor=[{"action": "rewind", "target": "writer", "instructions": ["cut line 1 to 90 characters"],
                             "reason": "weak hook"}]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch(), dry_run=True)
            self.assertTrue(res["ok"], res)
            second = [c for c in llm.calls if c["agent"] == "writer"][1]["prompt"]
            self.assertIn("SENT BACK by Quinn (Editor Review).\nWHY IT FAILED:\n- reviewer overall score 60", second)
            self.assertIn("THE REVIEWER'S FIXES - apply each one exactly as written", second)
            self.assertIn("- shorten the hook", second)                  # the Editor's fix, word for word
            mem = json.loads((ws.runs_dir / res["run_id"] / "memory.json").read_text())
            self.assertEqual([(m["step"], m["kind"]) for m in mem if m["kind"] == "sent_back"], [("writer", "sent_back")])
            self.assertTrue(any(r["fix"] == ["shorten the hook"] for r in ws.state("memory", {})["writer"]))
            # the next run's writer starts with what was learned
            llm2 = ScriptedLLM(self.script())
            res2 = run_crew(ws, TUESDAY + timedelta(days=7), llm=llm2, fetch=fake_fetch(), dry_run=True)
            first = next(c for c in llm2.calls if c["agent"] == "writer")["prompt"]
            self.assertIn("CREW MEMORY", first)
            self.assertIn("fixed by: shorten the hook", first)
            self.assertNotIn("WHY IT FAILED", first)
            self.assertTrue(res2["ok"], res2)

    def test_editor_sees_its_previous_rounds(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(editor=[review(60, fixes=["Replace line 1 with: 'Acme Model 2: $0.10'"])] * 1
                                          + [review()]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch(), dry_run=True)
            self.assertTrue(res["ok"], res)
            eds = [c["prompt"] for c in llm.calls if c["agent"] == "editor"]
            self.assertNotIn("<previous_rounds>", eds[0])
            self.assertIn("<previous_rounds>", eds[3])
            self.assertIn("fix asked: Replace line 1 with: 'Acme Model 2: $0.10'", eds[3])
            self.assertIn("HOW EVERY POST IS SCORED", llm.calls[[c["agent"] for c in llm.calls].index("writer")]["system"])

    def test_gives_up_after_max_attempts_and_notifies(self, _):
        with TempWorkspace() as ws:
            llm = ScriptedLLM(self.script(writer=[writer("Too short.")]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertFalse(res["ok"])
            self.assertEqual(res["failed_step"], "writer")
            st = status(ws, res["run_id"])
            self.assertEqual(st["steps"]["writer"]["attempts"], ws.config()["pipeline"]["max_attempts_per_step"])
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

    def test_research_always_runs_even_if_an_old_config_turned_it_off(self, _):
        with TempWorkspace() as ws:
            spec = {"layout": "code", "title": "Default arguments are [[shared]]", "language": "python",
                    "code": "def add(item, items=None):\n    if items is None:\n        items = []\n    items.append(item)\n    return items",
                    "caption": "Use None, then create the list inside"}
            cfg = ws.config()
            cfg["categories"]["dev-tip"]["research"] = "off"
            ws.save_config(cfg)
            llm = ScriptedLLM(self.script(topic=[topic("Mutable default arguments in Python", [])],
                                          writer=[writer(DEV_TIP, "")], media=[spec]))
            res = run_crew(ws, SATURDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            self.assertEqual(status(ws, res["run_id"])["steps"]["research"]["state"], "passed")
            self.assertEqual(ws.config()["categories"]["dev-tip"]["research"], "optional")

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

    def live(self, ws):
        p = self.queue_one(ws, dry=False)
        ws.update_secrets(linkedin_client_id="abcdefgh12", linkedin_client_secret="s", linkedin_access_token="good",
                          linkedin_token_expires_at=(datetime.now(timezone.utc) + timedelta(days=50)).isoformat())
        FakeLinkedIn.posts, FakeLinkedIn.comments = [], []
        return datetime.fromisoformat(p["scheduled_at"]) + timedelta(minutes=1)

    def test_first_comment_is_added_after_publishing_and_retried_if_linkedin_refuses(self, _):
        with TempWorkspace() as ws, mock.patch.object(cred_mod, "LinkedIn", FakeLinkedIn):
            at, waits = self.live(ws), []
            FakeLinkedIn.comment_failures = 1                        # not accepted right away; the retry works
            publish_due(ws, now=at, client_factory=FakeLinkedIn, log=lambda m: None, sleep=waits.append)
            self.assertEqual(FakeLinkedIn.comments, [{"urn": "urn:li:share:1", "text": PAGE_URL}])
            self.assertEqual((ws.history()[0]["comment_status"], waits), ("added", [5]))

    def test_failed_first_comment_is_retried_on_the_next_publish_check(self, _):
        with TempWorkspace() as ws, mock.patch.object(cred_mod, "LinkedIn", FakeLinkedIn):
            at = self.live(ws)
            FakeLinkedIn.comment_failures = 3                        # every try in the publish window fails
            publish_due(ws, now=at, client_factory=FakeLinkedIn, log=lambda m: None, sleep=lambda s: None)
            h = ws.history()[0]
            self.assertEqual((h["comment_status"], h["comment_tries"], FakeLinkedIn.comments), ("failed", 1, []))
            publish_due(ws, now=at + timedelta(minutes=15), client_factory=FakeLinkedIn, log=lambda m: None)
            self.assertEqual(ws.history()[0]["comment_status"], "added")
            self.assertEqual(len(FakeLinkedIn.comments), 1)
            self.assertEqual(len(FakeLinkedIn.posts), 1)             # the post itself is never sent again

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


class FixPickingTests(unittest.TestCase):
    def test_one_fix_per_failing_criterion_lowest_first(self):
        from postcrew.agents.editor import pick_fixes
        pl = {"min_overall": 80, "min_subscore": 70}
        def run(scores, fixes, flags=()):
            return {"scores": scores, "fixes": [{"criterion": c, "fix": f} for c, f in fixes], "red_flags": list(flags)}
        base = {"accuracy": 90, "clarity": 76, "hook": 66, "value": 85, "tone": 90, "format": 88}
        runs = [run(base, [("hook", "hook A"), ("clarity", "clarity A"), ("tone", "tone A")]),
                run(dict(base, hook=70), [("hook", "hook B"), ("value", "value B")])]
        scores = {k: min(r["scores"][k] for r in runs) for k in base}
        # the hook fix comes from the review that scored the hook lowest; passing criteria get no fix
        self.assertEqual(pick_fixes(runs, scores, pl), ["hook: hook A", "clarity: clarity A"])
        flagged = runs + [run(base, [("red_flag", "delete the unsupported claim")], flags=["unsupported_claim"])]
        self.assertEqual(pick_fixes(flagged, scores, pl)[0], "red_flag: delete the unsupported claim")
        self.assertEqual(pick_fixes(runs, scores, pl, target=86), ["hook: hook A", "clarity: clarity A", "value: value B"])
