"""Workspace, settings validation, credential monitor, scheduler, LLM wrapper and Studio API."""
import copy
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from helpers import FakeLinkedIn, TempWorkspace, claude_ok
from postcrew import crew, notify, scheduler
from postcrew.agents import credentials as cred_mod
from postcrew.defaults import DEFAULT_CONFIG
from postcrew.llm import ClaudeCode, LLMError
from postcrew.studio.server import ThreadingHTTPServer, Studio, make_handler
from postcrew.workspace import validate_config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(validate_config(copy.deepcopy(DEFAULT_CONFIG)), [])

    def test_bad_values_are_reported(self):
        c = copy.deepcopy(DEFAULT_CONFIG)
        c["schedule"]["timezone"] = "Mars/Base"
        c["schedule"]["post_time"] = "25:00"
        c["schedule"]["days"]["mon"] = "nope"
        c["categories"]["ai-news"]["max_chars"] = 5000
        c["publishing"]["approval"] = "sometimes"
        c["llm"]["agents"]["writer"]["timeout_s"] = 5
        errs = "\n".join(validate_config(c))
        for frag in ("timezone", "post_time", "unknown category 'nope'", "3000", "approval", "timeout_s"):
            self.assertIn(frag, errs)

    def test_save_refuses_invalid_config(self):
        with TempWorkspace() as ws:
            c = ws.config()
            c["schedule"]["lead_days"] = 99
            with self.assertRaises(ValueError):
                ws.save_config(c)

    def test_secrets_file_is_private_and_masked(self):
        with TempWorkspace() as ws:
            ws.update_secrets(linkedin_client_id="abcdefgh12", linkedin_client_secret="topsecret",
                              linkedin_access_token="ACCESS-TOKEN-VALUE")
            self.assertEqual(os.stat(ws.root / "secrets.json").st_mode & 0o777, 0o600)
            m = ws.masked_secrets()
            self.assertEqual(m["linkedin_client_id"], "abcdefgh12")
            self.assertIs(m["linkedin_client_secret"], True)
            self.assertNotIn("topsecret", json.dumps(m))
            self.assertNotIn("ACCESS-TOKEN-VALUE", json.dumps(m))


class CredentialTests(unittest.TestCase):
    def check(self, ws, **secrets):
        ws.update_secrets(**secrets)
        with mock.patch.object(cred_mod, "check_claude", return_value={"state": "ok", "message": "ok"}):
            return cred_mod.run_check(ws, client_factory=FakeLinkedIn)

    def future(self, days):
        return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    def test_states(self):
        with TempWorkspace() as ws:
            self.assertEqual(self.check(ws)["linkedin"]["state"], "missing")
            app = dict(linkedin_client_id="abcdefgh12", linkedin_client_secret="s")
            self.assertEqual(self.check(ws, **app, linkedin_access_token="good",
                                        linkedin_token_expires_at=self.future(40))["linkedin"]["state"], "ok")
            self.assertEqual(self.check(ws, linkedin_token_expires_at=self.future(3))["linkedin"]["state"], "expiring")
            self.assertEqual(self.check(ws, linkedin_token_expires_at=self.future(-2))["linkedin"]["state"], "expired")
            st = self.check(ws, linkedin_access_token="bad", linkedin_token_expires_at=self.future(40))
            self.assertEqual(st["linkedin"]["state"], "invalid")
            self.assertFalse(st["ok"])

    def test_problem_notifies_once_per_day(self):
        with TempWorkspace() as ws:
            for _ in range(3):
                self.check(ws, linkedin_client_id="abcdefgh12", linkedin_client_secret="s",
                           linkedin_access_token="bad", linkedin_token_expires_at=self.future(40))
            notes = [n for n in ws.state("notifications")["items"] if n["key"] == "linkedin-invalid"]
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["action"]["tab"], "credentials")

    def test_claude_login_check(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        with mock.patch("shutil.which", return_value="/bin/claude"):
            self.assertEqual(cred_mod.check_claude(cfg, runner=claude_ok)["state"], "ok")

            def logged_out(cmd, **kw):
                class R:
                    stdout = '{"loggedIn": false}'
                return R()
            self.assertEqual(cred_mod.check_claude(cfg, runner=logged_out)["state"], "logged_out")


class FakeSMTP:
    sent = []

    def __init__(self, host, port, context=None, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        if password != "abcdefghijklmnop":
            raise OSError("535 Username and Password not accepted")
        self.user = user

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


class EmailTests(unittest.TestCase):
    def setUp(self):
        FakeSMTP.sent = []
        patcher = mock.patch.object(notify, "SMTP", FakeSMTP)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sends_only_when_switched_on_and_configured(self):
        with TempWorkspace() as ws:
            ws.update_secrets(gmail_address="me@gmail.com", gmail_app_password="abcd efgh ijkl mnop")
            notify.notify(ws, "Post ready", "queued")
            self.assertEqual(FakeSMTP.sent, [])
            cfg = ws.config()
            cfg["notifications"].update(email=True, desktop=False)
            ws.save_config(cfg)
            notify.notify(ws, "Post ready", "queued for 08:30")
            msg = FakeSMTP.sent[0]
            self.assertEqual((msg["To"], msg["Subject"]), ("me@gmail.com", "Postcrew: Post ready"))
            self.assertIn("queued for 08:30", msg.get_body(("plain",)).get_content())
            self.assertIn("queued for 08:30", msg.get_body(("html",)).get_content())

    def test_email_is_html_with_a_table_the_post_and_its_poster(self):
        with TempWorkspace() as ws:
            ws.update_secrets(gmail_address="me@gmail.com", gmail_app_password="abcdefghijklmnop")
            cfg = ws.config()
            cfg["notifications"].update(email=True, desktop=False, studio_url="http://localhost:9000")
            ws.save_config(cfg)
            poster = ws.root / "media" / "p.png"
            poster.parent.mkdir(exist_ok=True)
            __import__("PIL.Image").Image.new("RGB", (8, 8), "white").save(poster)
            notify.notify(ws, "Post ready", "Acme <Model 2> pricing", action={"label": "Review in Queue", "tab": "queue"},
                          details={"rows": [("Topic", "Acme & co"), ("Editor score", "88 / 100")],
                                   "text": "Line one\nLine two", "image": str(poster)})
            msg = FakeSMTP.sent[0]
            page = msg.get_body(("html",)).get_content()
            self.assertIn("<td", page)
            self.assertIn("Editor score", page)
            self.assertIn("Acme &amp; co", page)                    # values are escaped
            self.assertIn("Acme &lt;Model 2&gt; pricing", page)
            self.assertIn("Line one<br>Line two", page)
            self.assertIn('href="http://localhost:9000/#queue"', page)
            cid = page.split('src="cid:')[1].split('"')[0]
            images = [p for p in msg.walk() if p.get_content_type() == "image/png"]
            self.assertEqual(images[0]["Content-ID"], f"<{cid}>")
            text = msg.get_body(("plain",)).get_content()
            self.assertIn("Editor score  88 / 100", text)            # the plain part is tabulated too
            self.assertIn("Line two", text)
            self.assertEqual(ws.state("notifications")["items"][-1]["rows"][1], ["Editor score", "88 / 100"])

    def test_reports_a_wrong_password_and_hides_it(self):
        with TempWorkspace() as ws:
            ws.update_secrets(gmail_address="me@gmail.com", gmail_app_password="wrong", email_to="you@example.com")
            self.assertIn("535", notify._gmail("me@gmail.com", "wrong", None, "s", "b"))
            m = ws.masked_secrets()
            self.assertEqual((m["gmail_address"], m["email_to"], m["gmail_app_password"]),
                             ("me@gmail.com", "you@example.com", True))


class SchedulerTests(unittest.TestCase):
    def test_generates_publishes_and_checks_on_time_once(self):
        with TempWorkspace() as ws:
            tz = ZoneInfo(ws.config()["schedule"]["timezone"])
            calls = []
            kw = dict(runner=lambda ws_, d: calls.append(("run", d.isoformat())),
                      publisher=lambda ws_: calls.append(("publish",)) or [],
                      checker=lambda ws_: calls.append(("check",)),
                      planner=lambda ws_, d: calls.append(("plan", d.isoformat())))
            scheduler.tick(ws, datetime(2026, 10, 12, 8, 0, tzinfo=tz), **kw)    # Monday 08:00: nothing yet
            self.assertEqual(calls, [])
            scheduler.tick(ws, datetime(2026, 10, 12, 9, 5, tzinfo=tz), **kw)    # after post_time + check time
            self.assertEqual(calls, [("check",), ("publish",)])
            scheduler.tick(ws, datetime(2026, 10, 12, 10, 1, tzinfo=tz), **kw)   # Monday 10:00: plan the week
            self.assertIn(("plan", "2026-10-12"), calls)
            scheduler.tick(ws, datetime(2026, 10, 12, 19, 1, tzinfo=tz), **kw)   # generate Tuesday's post
            self.assertIn(("run", "2026-10-13"), calls)
            n = len(calls)
            scheduler.tick(ws, datetime(2026, 10, 12, 19, 2, tzinfo=tz), **kw)   # no duplicates a minute later
            self.assertEqual(len(calls), n)
            self.assertEqual(calls.count(("plan", "2026-10-12")), 1)

    def test_does_not_generate_when_the_day_already_has_a_post(self):
        with TempWorkspace() as ws:
            tz = ZoneInfo(ws.config()["schedule"]["timezone"])
            calls = []
            kw = dict(runner=lambda ws_, d: calls.append(d.isoformat()), publisher=lambda ws_: [],
                      checker=lambda ws_: None, planner=lambda ws_, d: None)
            evening = datetime(2026, 10, 12, 19, 1, tzinfo=tz)                  # generates Tuesday 2026-10-13
            ws.save_queue([{"id": "a", "date": "2026-10-13", "status": "queued"}])    # made by a manual run
            scheduler.tick(ws, evening, **kw)
            ws.save_queue([])
            ws.add_history({"id": "a", "date": "2026-10-13", "status": "published"})  # ...and already published
            scheduler.tick(ws, evening, **kw)
            self.assertEqual(calls, [])
            ws.remove_history(lambda p: True)
            with crew._running:                                                  # a manual run is still going
                scheduler.tick(ws, evening, **kw)
            self.assertEqual(calls, [])
            scheduler.tick(ws, evening, **kw)                                    # nothing there and nothing running
            self.assertEqual(calls, ["2026-10-13"])

    def test_pause_stops_everything(self):
        with TempWorkspace() as ws:
            (ws.root / "PAUSE").write_text("")
            self.assertEqual(scheduler.tick(ws), ["paused"])


class LLMTests(unittest.TestCase):
    def run_with(self, stdout, returncode=0, stderr=""):
        class R:
            pass
        r = R()
        r.stdout, r.returncode, r.stderr = stdout, returncode, stderr
        cc = ClaudeCode(copy.deepcopy(DEFAULT_CONFIG), runner=lambda *a, **k: r)
        with mock.patch("shutil.which", return_value="/bin/claude"):
            return cc.call("writer", "sys", "hi", {"type": "object"}, tools=["WebFetch"])

    def test_parses_structured_output_and_cost(self):
        res = self.run_with(json.dumps({"subtype": "success", "is_error": False, "structured_output": {"a": 1},
                                        "total_cost_usd": 0.02, "num_turns": 2, "modelUsage": {"claude-x": {}}}))
        self.assertEqual((res.data, res.cost_usd, res.model), ({"a": 1}, 0.02, "claude-x"))

    def test_error_kinds(self):
        with self.assertRaises(LLMError) as e:
            self.run_with(json.dumps({"subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 1.0}))
        self.assertEqual(e.exception.kind, "budget")
        with self.assertRaises(LLMError) as e:  # Claude Code reports a used-up plan limit as "success" + is_error
            self.run_with(json.dumps({"subtype": "success", "is_error": True,
                                      "result": "You've hit your session limit · resets 3:40am (America/Chicago)"}))
        self.assertEqual(e.exception.kind, "limit")
        with self.assertRaises(LLMError) as e:
            self.run_with("", 1, "Please run /login")
        self.assertEqual(e.exception.kind, "auth")

    def test_command_is_isolated_and_limited(self):
        cc = ClaudeCode(copy.deepcopy(DEFAULT_CONFIG))
        cmd, timeout = cc.command("research", "sys", {"type": "object"}, ["WebSearch", "WebFetch"])
        for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence", "--json-schema",
                     "--max-budget-usd"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch,WebFetch")
        self.assertEqual(timeout, 900)


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tw = TempWorkspace()
        self.ws = self.tw.__enter__()
        self.studio = Studio(self.ws, 0)
        handler = make_handler(self.studio)
        handler.log_message = lambda *a: None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.studio.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.studio.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tw.__exit__()

    def req(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json", "X-Postcrew": "1"}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                   method=method, headers={k: v for k, v in h.items() if v is not None})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}")

    def test_pages_and_overview(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(b"Postcrew Studio", r.read())
        code, o = self.req("GET", "/api/overview")
        self.assertEqual(code, 200)
        self.assertTrue(o["dry_run"])

    def test_mutations_need_header_and_local_origin(self):
        self.assertEqual(self.req("PUT", "/api/credentials", {"telegram_chat_id": "1"}, {"X-Postcrew": None})[0], 403)
        self.assertEqual(self.req("PUT", "/api/credentials", {"telegram_chat_id": "1"},
                                  {"Origin": "https://evil.example"})[0], 403)

    def test_secrets_are_write_only(self):
        code, d = self.req("PUT", "/api/credentials", {"linkedin_client_id": "abcdefgh12",
                                                       "linkedin_client_secret": "supersecret"})
        self.assertEqual(code, 200)
        self.assertNotIn("supersecret", json.dumps(d))
        self.assertEqual(self.ws.secrets()["linkedin_client_secret"], "supersecret")
        code, d = self.req("PUT", "/api/credentials", {"linkedin_access_token": "x"})
        self.assertEqual(code, 400)

    def test_plan_edit_suggest_and_clear(self):
        from helpers import ScriptedLLM
        from postcrew.agents import planner
        code, d = self.req("GET", "/api/plan")
        self.assertEqual(code, 200)
        self.assertEqual(len(d["days"]), 7)                                  # Monday-Sunday of this week only
        cfg = self.ws.config()
        cfg["schedule"]["days"] = {k: "dev-tip" for k in cfg["schedule"]["days"]}   # every day open for edits
        self.ws.save_config(cfg)
        d = self.req("GET", "/api/plan")[1]
        open_days = [r["date"] for r in d["days"] if not r["past"]]
        if len(open_days) < 2:
            self.skipTest("run on Saturday or Sunday: too few days left this week")
        day, day2 = open_days[:2]
        code, d = self.req("PUT", "/api/plan", {"days": {day: {"topic": "Python walrus operator"},
                                                         day2: {"topic": "Git stash in 2 minutes"}}})
        self.assertEqual(code, 200)
        self.assertEqual(planner.load_plan(self.ws)[day2]["topic"], "Git stash in 2 minutes")
        code, _ = self.req("PUT", "/api/plan", {"days": {day: {"topic": "Docker tips"}, day2: {"topic": "x"}}})
        self.assertEqual(code, 400)                                           # one bad day: nothing saved
        self.assertEqual(planner.load_plan(self.ws)[day]["topic"], "Python walrus operator")
        past = next((r["date"] for r in d["days"] if r["past"]), None)
        if past:
            self.assertEqual(self.req("PUT", "/api/plan", {"days": {past: {"topic": "Too late topic"}}})[0], 400)
        code, d = self.req("PUT", f"/api/plan/{day}", {"topic": "Python walrus operator", "angle": "when := helps"})
        e = next(r for r in d["days"] if r["date"] == day)["entry"]
        self.assertEqual((e["topic"], e["source"]), ("Python walrus operator", "manual"))
        self.assertEqual(self.req("PUT", f"/api/plan/{day}", {"topic": "x"})[0], 400)
        llm = ScriptedLLM({"planner": [{"days": [{"date": day, "topic": "Git bisect in five minutes", "angle": "find "
                                                  "the bad commit", "search_queries": []}]}]})
        with mock.patch("postcrew.llm.make_backend", return_value=llm):
            code, d = self.req("POST", f"/api/plan/{day}/suggest", {"hint": "something about git"})
        e = next(r for r in d["days"] if r["date"] == day)["entry"]
        self.assertEqual((e["topic"], e["rejected"]), ("Git bisect in five minutes", ["Python walrus operator"]))
        self.assertIn("something about git", llm.calls[0]["prompt"])
        self.req("PUT", f"/api/plan/{day}", {"topic": ""})
        self.assertNotIn(day, planner.load_plan(self.ws))
        self.assertEqual(self.req("PUT", "/api/plan/2020-01-01", {"topic": "Old day topic"})[0], 400)

    def test_published_list_add_and_remove(self):
        from postcrew.checks import repeat_problem
        code, d = self.req("POST", "/api/history", {"date": "2026-10-01", "topic": "Kafka consumer groups",
                                                    "category": "dev-tip"})
        self.assertEqual(code, 200)
        h = d["history"][-1]
        self.assertTrue(h["added_by_hand"])
        self.assertTrue(repeat_problem("Kafka consumer groups", "", self.ws.recent_posts(60)))  # now a repeat
        self.assertEqual(self.req("POST", "/api/history", {"date": "2026-10-01", "topic": "x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/history", {"date": "yesterday", "topic": "Kafka again"})[0], 400)
        code, d = self.req("POST", "/api/history/remove", {"id": h["id"], "date": h["date"], "topic": h["topic"]})
        self.assertEqual((code, d["history"]), (200, []))
        self.assertIsNone(repeat_problem("Kafka consumer groups", "", self.ws.recent_posts(60)))  # allowed again
        self.assertEqual(self.req("POST", "/api/history/remove", {"id": h["id"], "date": h["date"],
                                                                  "topic": h["topic"]})[0], 404)

    def test_team_view_replace_hire_and_lessons(self):
        from postcrew.agents import team
        code, d = self.req("GET", "/api/team")
        self.assertEqual(code, 200)
        self.assertEqual([m["name"] for m in d["members"]], ["Ada", "Ravi", "Maya", "Leo"])
        self.assertEqual([m["working"] for m in d["members"] if m["role"] == "research"], [True, False])  # 1 per post
        team.record(self.ws, "writer-leo", "r1", good=False, problems=["vague hook"])
        with mock.patch("postcrew.llm.make_backend", side_effect=RuntimeError("offline")):
            code, d = self.req("POST", "/api/team/fire", {"id": "writer-leo"})
        self.assertEqual(code, 200)
        self.assertEqual([m["name"] for m in d["members"] if m["role"] == "writer"], ["Maya", "Nora"])
        self.assertEqual(d["lessons"]["writer"], ["Avoid this past problem: vague hook"])
        code, d = self.req("POST", "/api/team/hire", {"role": "writer"})
        self.assertEqual(len([m for m in d["members"] if m["role"] == "writer"]), 3)
        self.assertEqual(self.ws.config()["team"]["writer"], 2)          # one more works on each post
        code, d = self.req("POST", "/api/team/lesson-remove", {"role": "writer", "index": 0})
        self.assertEqual(d["lessons"]["writer"], [])
        self.assertEqual(self.req("POST", "/api/team/hire", {"role": "boss"})[0], 400)

    def test_agents_have_names_and_memory_can_be_forgotten(self):
        code, d = self.req("GET", "/api/agents")
        names = {a["id"]: a["name"] for a in d["agents"]}
        self.assertEqual((names["supervisor"], names["editor"], names["reviewer"]), ("Orion", "Quinn", "Iris"))
        self.assertEqual(next(a for a in d["agents"] if a["id"] == "research")["members"], ["Ada"])  # 1 per post
        self.ws.save_state("memory", {"writer": [{"problem": "hook too vague", "fix": ["name the product"], "at": "x"}]})
        code, d = self.req("GET", "/api/memory")
        self.assertEqual(d["memory"]["writer"][0]["problem"], "hook too vague")
        code, d = self.req("POST", "/api/memory/forget", {"step": "writer", "index": 0})
        self.assertEqual((code, d["memory"]["writer"]), (200, []))
        self.assertEqual(self.req("POST", "/api/memory/forget", {"step": "writer", "index": 5})[0], 404)

    def test_gmail_settings_and_test_email(self):
        self.assertEqual(self.req("POST", "/api/notifications/test-email")[1]["ok"], False)
        self.assertEqual(self.req("PUT", "/api/credentials", {"gmail_address": "not-an-email"})[0], 400)
        code, d = self.req("PUT", "/api/credentials", {"gmail_address": "me@gmail.com",
                                                       "gmail_app_password": "abcdefghijklmnop"})
        self.assertEqual(code, 200)
        self.assertNotIn("abcdefghijklmnop", json.dumps(d))
        with mock.patch.object(notify, "SMTP", FakeSMTP):
            code, d = self.req("POST", "/api/notifications/test-email")
        self.assertEqual((d["ok"], d["to"]), (True, "me@gmail.com"))

    def test_config_round_trip_and_validation(self):
        _, d = self.req("GET", "/api/config")
        cfg = d["config"]
        cfg["schedule"]["post_time"] = "07:45"
        self.assertTrue(self.req("PUT", "/api/config", {"config": cfg})[1]["ok"])
        self.assertEqual(self.ws.config()["schedule"]["post_time"], "07:45")
        cfg["schedule"]["post_time"] = "7.45"
        _, r = self.req("PUT", "/api/config", {"config": cfg})
        self.assertFalse(r["ok"])
        self.assertEqual(self.ws.config()["schedule"]["post_time"], "07:45")

    def test_oauth_rejects_unknown_state(self):
        self.ws.update_secrets(linkedin_client_id="abcdefgh12", linkedin_client_secret="s")
        with urllib.request.urlopen(self.base + "/oauth/callback?code=x&state=forged") as r:
            self.assertIn(b"sign-in failed", r.read())
        url = self.studio.oauth_start()
        self.assertIn("client_id=abcdefgh12", url)
        self.assertIn("w_member_social", url)

    def test_queue_actions(self):
        self.ws.save_queue([{"id": "p1", "status": "queued", "date": "2026-10-13", "scheduled_at": "2026-10-13T13:30:00+00:00",
                             "text": "hello", "topic": "t", "category": "ai-news"}])
        self.assertEqual(self.req("POST", "/api/queue/p1/veto", {})[1]["status"], "vetoed")
        self.assertEqual(self.req("POST", "/api/queue/p1/restore", {})[1]["status"], "queued")
        self.assertEqual(self.req("POST", "/api/queue/p1/edit", {"text": "new text"})[1]["text"], "new text")
        self.assertEqual(self.req("POST", "/api/queue/p1/edit", {"text": "x" * 3001})[0], 400)
        self.assertEqual(self.req("POST", "/api/queue/nope/veto", {})[0], 404)

    def test_run_files_cannot_escape_the_run_folder(self):
        (self.ws.runs_dir / "r1").mkdir()
        (self.ws.runs_dir / "r1" / "status.json").write_text("{}")
        code, _ = self.req("GET", "/api/runs/r1/file/..%2F..%2Fsecrets.json")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
