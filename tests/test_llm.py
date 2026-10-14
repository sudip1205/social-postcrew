"""The API backends (Claude API, OpenAI API, OpenAI-compatible) against a fake HTTP server. No network."""
import copy
import io
import json
import unittest
import urllib.error

from helpers import TempWorkspace
from postcrew.agents import credentials as cred_mod
from postcrew.defaults import DEFAULT_CONFIG
from postcrew.llm import LLMError, make_backend, parse_json
from postcrew.workspace import validate_config

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


class FakeHTTP:
    """Answers queued per URL path suffix; records every request."""

    def __init__(self, answers):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.requests = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode()) if req.data else None
        self.requests.append({"url": req.full_url, "headers": dict(req.header_items()), "body": body})
        path = next(k for k in self.answers if req.full_url.endswith(k))
        item = self.answers[path].pop(0) if len(self.answers[path]) > 1 else self.answers[path][0]
        if isinstance(item, int):
            raise urllib.error.HTTPError(req.full_url, item, "error", {}, io.BytesIO(b'{"error": "nope"}'))
        return io.BytesIO(json.dumps(item).encode())


def cfg_for(backend, **api):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["llm"]["backend"] = backend
    cfg["llm"]["api"].update(api)
    return cfg


class AnthropicTests(unittest.TestCase):
    def test_answer_comes_back_through_the_respond_tool_with_cost(self):
        http = FakeHTTP({"/messages": [{"content": [{"type": "tool_use", "name": "respond", "input": {"ok": True}}],
                                        "stop_reason": "tool_use", "model": "claude-sonnet-5-5",
                                        "usage": {"input_tokens": 1_000_000, "output_tokens": 100_000}}]})
        b = make_backend(cfg_for("anthropic"), {"anthropic_api_key": "sk-test"})
        b.opener = http
        res = b.call("writer", "sys", "hi", SCHEMA)
        self.assertEqual(res.data, {"ok": True})
        self.assertAlmostEqual(res.cost_usd, 3.0 + 1.5)               # sonnet tier -> $3 in / $15 out per Mtok
        req = http.requests[0]
        self.assertEqual(req["body"]["model"], "claude-sonnet-5-5")
        self.assertEqual(req["body"]["tool_choice"], {"type": "tool", "name": "respond"})
        self.assertEqual(req["headers"]["X-api-key"], "sk-test")

    def test_web_search_runs_server_side_then_it_must_answer_through_the_tool(self):
        http = FakeHTTP({"/messages": [
            {"content": [{"type": "server_tool_use", "name": "web_search"}], "stop_reason": "pause_turn",
             "usage": {"input_tokens": 10, "output_tokens": 5, "server_tool_use": {"web_search_requests": 2}}},
            {"content": [{"type": "text", "text": "Here is what I found"}], "stop_reason": "end_turn", "usage": {}},
            {"content": [{"type": "tool_use", "name": "respond", "input": {"ok": True}}], "stop_reason": "tool_use",
             "usage": {}}]})
        b = make_backend(cfg_for("anthropic"), {"anthropic_api_key": "k"})
        b.opener = http
        res = b.call("research", "sys", "find pages", SCHEMA, tools=["WebSearch"])
        self.assertEqual((res.data, res.turns), ({"ok": True}, 3))
        first, last = http.requests[0]["body"], http.requests[-1]["body"]
        self.assertEqual(first["tool_choice"], {"type": "auto"})
        self.assertIn("web_search", [t.get("name") for t in first["tools"]])
        self.assertEqual(last["tool_choice"], {"type": "tool", "name": "respond"})
        self.assertGreaterEqual(res.cost_usd, 0.02)                  # two searches

    def test_bad_key_and_missing_key_are_auth_errors(self):
        b = make_backend(cfg_for("anthropic"), {"anthropic_api_key": "bad"})
        b.opener = FakeHTTP({"/messages": [401]})
        with self.assertRaises(LLMError) as e:
            b.call("writer", "s", "p", SCHEMA)
        self.assertEqual(e.exception.kind, "auth")
        with self.assertRaises(LLMError) as e:
            make_backend(cfg_for("anthropic"), {}).call("writer", "s", "p", SCHEMA)
        self.assertEqual(e.exception.kind, "auth")

    def test_overloaded_is_retried(self):
        b = make_backend(cfg_for("anthropic"), {"anthropic_api_key": "k"})
        b.opener, b.sleep = FakeHTTP({"/messages": [529, {"content": [
            {"type": "tool_use", "name": "respond", "input": {"ok": True}}], "usage": {}}]}), lambda s: None
        self.assertEqual(b.call("writer", "s", "p", SCHEMA).data, {"ok": True})


class OpenAITests(unittest.TestCase):
    def test_responses_api_with_json_schema_and_web_search(self):
        http = FakeHTTP({"/responses": [{"status": "completed", "model": "gpt-5-mini", "output": [
            {"type": "web_search_call"},
            {"type": "message", "content": [{"type": "output_text", "text": '{"ok": true}'}]}],
            "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}]})
        b = make_backend(cfg_for("openai"), {"openai_api_key": "sk-o"})
        b.opener = http
        res = b.call("topic", "sys", "p", SCHEMA, tools=["WebSearch"])
        self.assertEqual(res.data, {"ok": True})
        body = http.requests[0]["body"]
        self.assertEqual(body["model"], "gpt-5-mini")
        self.assertEqual(body["text"]["format"]["schema"], SCHEMA)
        self.assertEqual(body["tools"], [{"type": "web_search"}])
        self.assertEqual(http.requests[0]["headers"]["Authorization"], "Bearer sk-o")
        self.assertAlmostEqual(res.cost_usd, 0.25 + 0.01)

    def test_out_of_quota_is_a_limit(self):
        b = make_backend(cfg_for("openai"), {"openai_api_key": "k"})

        def opener(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 429, "x", {}, io.BytesIO(b'{"code": "insufficient_quota"}'))
        b.opener = opener
        with self.assertRaises(LLMError) as e:
            b.call("writer", "s", "p", SCHEMA)
        self.assertEqual(e.exception.kind, "limit")


class CompatibleTests(unittest.TestCase):
    def cfg(self):
        return cfg_for("openai-compatible", base_url="http://localhost:11434/v1",
                       models={**DEFAULT_CONFIG["llm"]["api"]["models"],
                               "openai-compatible": {"opus": "qwen3:32b", "sonnet": "qwen3:14b", "haiku": "qwen3:4b"}})

    def test_falls_back_to_plain_json_when_the_server_has_no_json_schema(self):
        http = FakeHTTP({"/chat/completions": [400, {"model": "qwen3:14b", "choices": [
            {"finish_reason": "stop", "message": {"content": 'Sure!\n```json\n{"ok": true}\n```'}}]}]})
        b = make_backend(self.cfg(), {})
        b.opener = http
        res = b.call("research", "sys", "find pages", SCHEMA, tools=["WebSearch"])
        self.assertEqual(res.data, {"ok": True})
        self.assertEqual(http.requests[0]["url"], "http://localhost:11434/v1/chat/completions")
        self.assertEqual(http.requests[0]["body"]["model"], "qwen3:14b")
        self.assertEqual(http.requests[1]["body"]["response_format"], {"type": "json_object"})
        self.assertIn("web search is not available", http.requests[0]["body"]["messages"][1]["content"])
        self.assertNotIn("Authorization", http.requests[0]["headers"])   # no key needed for a local server

    def test_settings_must_name_the_server_and_its_models(self):
        cfg = cfg_for("openai-compatible")
        errs = " ".join(validate_config(cfg))
        self.assertIn("base_url", errs)
        self.assertIn("openai-compatible", errs)
        self.assertEqual(validate_config(self.cfg()), [])
        self.assertIn("llm.backend", " ".join(validate_config(cfg_for("gemini-magic"))))


class CheckTests(unittest.TestCase):
    def test_credential_check_lists_models_and_reports_a_bad_key(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["llm"]["backend"] = "openai"
            ws.save_config(cfg)
            self.assertEqual(cred_mod.check_ai(ws, ws.config())["state"], "missing")
            ws.update_secrets(openai_api_key="sk-x")
            ok = cred_mod.check_ai(ws, ws.config(), opener=FakeHTTP({"/models": [{"data": []}]}))
            self.assertEqual((ok["state"], ok["provider"]), ("ok", "OpenAI API"))
            bad = cred_mod.check_ai(ws, ws.config(), opener=FakeHTTP({"/models": [401]}))
            self.assertEqual(bad["state"], "invalid")
            self.assertNotIn("sk-x", json.dumps(ws.masked_secrets()))


class ParseTests(unittest.TestCase):
    def test_finds_the_json_object(self):
        self.assertEqual(parse_json('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_json('text ```json\n{"a": {"b": 2}}\n``` more'), {"a": {"b": 2}})
        self.assertIsNone(parse_json("no json here"))


if __name__ == "__main__":
    unittest.main()
