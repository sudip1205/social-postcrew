"""LLM backends. Every agent calls `call(agent_id, system, prompt, schema, tools)` and gets JSON that matches the schema.

  claude-code        the Claude Code CLI in headless mode (`claude -p`): your Claude Pro / Max / Team login, no API
                     key. Runs isolated: --restricted (no code-running tools, your user/project settings and hooks are
                     ignored), --strict-mcp-config (no MCP servers), and only the tools an agent is explicitly given.
  anthropic          the Claude API (api.anthropic.com) with an API key. Web search is Anthropic's server-side tool.
  openai             the OpenAI API (Responses API) with an API key. Web search is OpenAI's built-in tool.
  openai-compatible  any server that speaks the OpenAI Chat Completions API: Ollama, LM Studio, OpenRouter, Groq,
                     Together, vLLM, Azure OpenAI and others. These have no web search: the researchers then suggest
                     pages from what they know, and Postcrew still downloads every page and checks every quote itself.

Agents ask for models by tier (opus = strongest, sonnet = balanced, haiku = fastest) or by full model id;
llm.api.models maps the tiers to each provider's models. To add a backend, implement `call()` with the same
signature and register it in BACKENDS.
"""
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class LLMError(RuntimeError):
    """kind: timeout | auth | budget | limit | invalid_output | not_installed | failed
    (limit = the plan's usage limit or the API account's quota is used up; retrying before it resets cannot help)"""

    def __init__(self, message, kind="failed", cost_usd=0.0, status=None):
        super().__init__(message)
        self.kind = kind
        self.cost_usd = cost_usd
        self.status = status


@dataclass
class LLMResult:
    data: dict
    cost_usd: float = 0.0
    duration_s: float = 0.0
    model: str = ""
    turns: int = 0
    raw: dict = field(default_factory=dict)


def agent_settings(cfg, agent_id):
    llm = cfg["llm"]
    return {**llm.get("defaults", {}), **llm.get("agents", {}).get(agent_id, {})}


class ClaudeCode:
    name = "claude-code"

    def __init__(self, cfg, runner=subprocess.run):
        self.cfg = cfg
        self.binary = cfg["llm"].get("claude_path") or "claude"
        self.runner = runner

    def available(self):
        return shutil.which(self.binary) is not None

    def command(self, agent_id, system, schema, tools, model=None):
        s = agent_settings(self.cfg, agent_id)
        if model:
            s["model"] = model
        cmd = [self.binary, "-p", "--output-format", "json", "--no-session-persistence",
               "--restricted", "--strict-mcp-config",
               "--model", str(s.get("model", "sonnet")),
               "--max-budget-usd", str(s.get("max_budget_usd", 1.0)),
               "--system-prompt", system,
               "--json-schema", json.dumps(schema),
               "--tools", ",".join(tools)]
        if tools:
            cmd += ["--allowedTools", ",".join(tools)]
        return cmd, int(s.get("timeout_s", 600))

    def call(self, agent_id, system, prompt, schema, tools=(), cwd=None, model=None, member=None):
        """model: override the agent's model (a team member's own model). member: for logs and test doubles."""
        if not self.available():
            raise LLMError(f"Claude Code CLI '{self.binary}' not found. Install it (https://claude.com/claude-code) "
                           f"and run `claude` once to log in.", kind="not_installed")
        cmd, timeout = self.command(agent_id, system, schema, list(tools), model)
        t0 = time.time()
        try:
            r = self.runner(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        except subprocess.TimeoutExpired:
            raise LLMError(f"no answer within {timeout}s", kind="timeout")
        dt = time.time() - t0
        try:
            out = json.loads(r.stdout)
        except ValueError:
            msg = (r.stderr or r.stdout or "").strip()[-500:]
            kind = "auth" if any(w in msg.lower() for w in ("log in", "login", "authenticat", "/login")) else "failed"
            raise LLMError(f"claude exited {r.returncode}: {msg or 'no output'}", kind=kind)
        cost = float(out.get("total_cost_usd") or 0.0)
        if out.get("is_error") or out.get("subtype") != "success":
            sub = out.get("subtype", "")
            text = str(out.get("result") or out.get("api_error_status") or sub)[:400]
            low = text.lower()
            if re.search(r"(session|usage|weekly|rate) limit|limit .*resets", low):
                raise LLMError(f"your Claude usage limit is used up: {text}", kind="limit", cost_usd=cost)
            kind = "budget" if "budget" in sub else ("auth" if "auth" in low or "login" in low else "failed")
            raise LLMError(f"claude reported {sub or 'an error'}: {text}", kind=kind, cost_usd=cost)
        data = out.get("structured_output")
        if not isinstance(data, dict):
            try:
                data = json.loads(out.get("result") or "")
            except ValueError:
                raise LLMError("the model did not return JSON matching the schema", kind="invalid_output",
                               cost_usd=cost)
        model = next(iter(out.get("modelUsage") or {}), "")
        return LLMResult(data=data, cost_usd=cost, duration_s=round(dt, 1), model=model,
                         turns=int(out.get("num_turns") or 0), raw={k: out.get(k) for k in ("session_id", "usage")})


TIERS = ("opus", "sonnet", "haiku")
KEY_SECRET = {"anthropic": "anthropic_api_key", "openai": "openai_api_key", "openai-compatible": "llm_api_key"}
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "openai-compatible": "LLM_API_KEY"}
DEFAULT_URL = {"anthropic": "https://api.anthropic.com/v1", "openai": "https://api.openai.com/v1"}
SEARCH_USD = 0.01  # web search, per search (both providers charge about $10 per 1,000)
NO_SEARCH_NOTE = ("\n\nNOTE: web search is not available with this AI provider. Suggest only pages you are confident "
                  "exist (official announcements, docs, release notes, repositories); every page is downloaded and "
                  "checked, and pages that do not exist are rejected.")


def parse_json(text):
    """The first JSON object in a model's text answer (tolerates ```json fences and words around it)."""
    text = (text or "").strip()
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except ValueError:
        pass
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        try:
            out = json.loads(text[a:b + 1])
            if isinstance(out, dict):
                return out
        except ValueError:
            pass
    return None


class APIBackend:
    """Shared by the HTTP backends: settings, model tiers, the API key, retries, errors and cost."""
    name = ""

    def __init__(self, cfg, secrets=None, opener=urllib.request.urlopen, sleep=time.sleep):
        import os
        self.cfg, self.opener, self.sleep = cfg, opener, sleep
        self.api = cfg["llm"].get("api", {})
        self.base = (self.api.get("base_url") or DEFAULT_URL.get(self.name, "")).rstrip("/")
        self.key = (secrets or {}).get(KEY_SECRET[self.name]) or os.environ.get(KEY_ENV[self.name], "")

    def available(self):
        return bool(self.key) or self.name == "openai-compatible"

    def model_id(self, agent_id, model=None):
        m = model or agent_settings(self.cfg, agent_id).get("model", "sonnet")
        return (self.api.get("models", {}).get(self.name) or {}).get(m) or m

    def cost(self, model, tokens_in, tokens_out, searches=0):
        p = self.api.get("prices", {}).get(model) or {}
        return round(tokens_in / 1e6 * p.get("input", 0) + tokens_out / 1e6 * p.get("output", 0)
                     + searches * SEARCH_USD, 6)

    def headers(self):
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    def post(self, path, body, timeout, tries=3):
        req = lambda: urllib.request.Request(f"{self.base}{path}", data=json.dumps(body).encode(), method="POST",
                                             headers={"Content-Type": "application/json", **self.headers()})
        for i in range(tries):
            try:
                with self.opener(req(), timeout=timeout) as r:
                    return json.loads(r.read().decode() or "{}")
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:400] if hasattr(e, "read") else ""
                low = detail.lower()
                if e.code in (401, 403):
                    raise LLMError(f"{self.name} rejected the API key (HTTP {e.code}): {detail}", kind="auth")
                if e.code == 429 and any(w in low for w in ("insufficient_quota", "credit", "billing", "quota")):
                    raise LLMError(f"{self.name} account is out of credit or quota: {detail}", kind="limit")
                if e.code in (408, 429, 500, 502, 503, 504, 529) and i < tries - 1:
                    self.sleep(5 * (i + 1) ** 2)
                    continue
                raise LLMError(f"{self.name} HTTP {e.code}: {detail}", kind="failed", status=e.code)
            except (TimeoutError, OSError) as e:
                if "timed out" in str(e).lower():
                    raise LLMError(f"no answer within {timeout}s", kind="timeout")
                if i < tries - 1:
                    self.sleep(5)
                    continue
                raise LLMError(f"could not reach {self.base}: {e}", kind="failed")

    def settings(self, agent_id, model):
        s = agent_settings(self.cfg, agent_id)
        return (self.model_id(agent_id, model), int(s.get("timeout_s", 600)), float(s.get("max_budget_usd", 1.0)),
                int(self.api.get("max_output_tokens", 16000)))

    def call(self, agent_id, system, prompt, schema, tools=(), cwd=None, model=None, member=None):
        if not self.available():
            raise LLMError(f"no {self.name} API key: add it in Studio > Credentials (or set {KEY_ENV[self.name]})",
                           kind="auth")
        t0 = time.time()
        res = self.ask(agent_id, system, prompt, schema, list(tools), model)
        res.duration_s = round(time.time() - t0, 1)
        return res


class Anthropic(APIBackend):
    """Claude API. The answer comes back as the input of a `respond` tool whose input_schema is the agent's schema."""
    name = "anthropic"

    def headers(self):
        return {"x-api-key": self.key, "anthropic-version": "2023-06-01"}

    def ask(self, agent_id, system, prompt, schema, tools, model):
        model, timeout, budget, max_tokens = self.settings(agent_id, model)
        search = "WebSearch" in tools
        spec = [{"name": "respond", "description": "Return your final answer. Call this exactly once, at the end.",
                 "input_schema": schema}]
        if search:
            spec.append({"type": "web_search_20250305", "name": "web_search", "max_uses": 5})
        messages, cost, turns, force = [{"role": "user", "content": prompt}], 0.0, 0, not search
        while turns < 8:
            turns += 1
            r = self.post("/messages", {"model": model, "max_tokens": max_tokens, "system": system,
                                        "messages": messages, "tools": spec,
                                        "tool_choice": {"type": "tool", "name": "respond"} if force else {"type": "auto"}},
                          timeout)
            u = r.get("usage") or {}
            cost += self.cost(model, u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                              + u.get("cache_creation_input_tokens", 0), u.get("output_tokens", 0),
                              (u.get("server_tool_use") or {}).get("web_search_requests", 0))
            for block in r.get("content") or []:
                if block.get("type") == "tool_use" and block.get("name") == "respond":
                    return LLMResult(data=block.get("input") or {}, cost_usd=cost, model=r.get("model", model),
                                     turns=turns, raw={"usage": u})
            if cost > budget:
                raise LLMError(f"over this call's budget (${budget:.2f})", kind="budget", cost_usd=cost)
            if r.get("stop_reason") == "max_tokens":
                raise LLMError("the answer was cut off (raise llm.api.max_output_tokens)", kind="invalid_output",
                               cost_usd=cost)
            messages.append({"role": "assistant", "content": r.get("content") or []})
            if r.get("stop_reason") != "pause_turn":  # it answered in text: ask for the tool call now
                messages.append({"role": "user", "content": "Now call the respond tool with your final answer."})
                force = True
        raise LLMError("no answer after 8 turns", kind="invalid_output", cost_usd=cost)


class OpenAI(APIBackend):
    """OpenAI Responses API with a JSON-schema answer format."""
    name = "openai"

    def ask(self, agent_id, system, prompt, schema, tools, model):
        model, timeout, budget, max_tokens = self.settings(agent_id, model)
        body = {"model": model, "instructions": system, "input": prompt, "max_output_tokens": max_tokens,
                "text": {"format": {"type": "json_schema", "name": "answer", "schema": schema, "strict": False}}}
        if "WebSearch" in tools:
            body["tools"] = [{"type": "web_search"}]
        r = self.post("/responses", body, timeout)
        u = r.get("usage") or {}
        out = r.get("output") or []
        cost = self.cost(model, u.get("input_tokens", 0), u.get("output_tokens", 0),
                         sum(1 for o in out if o.get("type") == "web_search_call"))
        if r.get("status") == "incomplete":
            why = (r.get("incomplete_details") or {}).get("reason", "")
            raise LLMError(f"the answer was cut off ({why}; raise llm.api.max_output_tokens)", kind="invalid_output",
                           cost_usd=cost)
        text = "".join(c.get("text", "") for o in out if o.get("type") == "message"
                       for c in o.get("content") or [] if c.get("type") == "output_text")
        data = parse_json(text)
        if data is None:
            raise LLMError("the model did not return JSON matching the schema", kind="invalid_output", cost_usd=cost)
        return LLMResult(data=data, cost_usd=cost, model=r.get("model", model), turns=1, raw={"usage": u})


class OpenAICompatible(APIBackend):
    """Chat Completions on any OpenAI-compatible server (llm.api.base_url). No web search."""
    name = "openai-compatible"

    def ask(self, agent_id, system, prompt, schema, tools, model):
        model, timeout, budget, max_tokens = self.settings(agent_id, model)
        if "WebSearch" in tools:
            prompt += NO_SEARCH_NOTE
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        body = {"model": model, "messages": messages, "max_tokens": max_tokens,
                "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}}
        try:
            r = self.post("/chat/completions", body, timeout)
        except LLMError as e:
            if e.status != 400:
                raise
            # this server does not support JSON schemas: ask for plain JSON and put the schema in the instructions
            body["messages"] = [{"role": "system", "content": f"{system}\n\nAnswer with one JSON object only, "
                                                              f"matching this JSON schema:\n{json.dumps(schema)}"},
                                messages[1]]
            body["response_format"] = {"type": "json_object"}
            r = self.post("/chat/completions", body, timeout)
        u = r.get("usage") or {}
        cost = self.cost(model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        choice = (r.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LLMError("the answer was cut off (raise llm.api.max_output_tokens)", kind="invalid_output",
                           cost_usd=cost)
        data = parse_json((choice.get("message") or {}).get("content"))
        if data is None:
            raise LLMError("the model did not return JSON matching the schema", kind="invalid_output", cost_usd=cost)
        return LLMResult(data=data, cost_usd=cost, model=r.get("model", model), turns=1, raw={"usage": u})


BACKENDS = {"claude-code": ClaudeCode, "anthropic": Anthropic, "openai": OpenAI, "openai-compatible": OpenAICompatible}


def make_backend(cfg, secrets=None):
    """secrets: the workspace's secrets (API keys); API keys may also come from the environment."""
    if cfg["llm"]["backend"] == "demo":
        from .demo import Demo
        return Demo(cfg, secrets)
    cls = BACKENDS[cfg["llm"]["backend"]]
    return cls(cfg) if cls is ClaudeCode else cls(cfg, secrets)
