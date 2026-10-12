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
from postcrew import scheduler
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


class SchedulerTests(unittest.TestCase):
    def test_generates_publishes_and_checks_on_time_once(self):
        with TempWorkspace() as ws:
            tz = ZoneInfo(ws.config()["schedule"]["timezone"])
            calls = []
            kw = dict(runner=lambda ws_, d: calls.append(("run", d.isoformat())),
                      publisher=lambda ws_: calls.append(("publish",)) or [],
                      checker=lambda ws_: calls.append(("check",)))
            scheduler.tick(ws, datetime(2026, 10, 12, 8, 0, tzinfo=tz), **kw)    # Monday 08:00: nothing yet
            self.assertEqual(calls, [])
            scheduler.tick(ws, datetime(2026, 10, 12, 9, 5, tzinfo=tz), **kw)    # after post_time + check time
            self.assertEqual(calls, [("check",), ("publish",)])
            scheduler.tick(ws, datetime(2026, 10, 12, 19, 1, tzinfo=tz), **kw)   # generate Tuesday's post
            self.assertIn(("run", "2026-10-13"), calls)
            n = len(calls)
            scheduler.tick(ws, datetime(2026, 10, 12, 19, 2, tzinfo=tz), **kw)   # no duplicates a minute later
            self.assertEqual(len(calls), n)

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
