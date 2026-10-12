"""LLM backend. Version 1 ships one backend: the Claude Code CLI in headless mode (`claude -p`).

It uses your Claude login (no API key), returns JSON that matches a schema, reports its cost, and runs
isolated: --restricted (no code-running tools, your user/project settings and hooks are ignored),
--strict-mcp-config (no MCP servers), and only the tools an agent is explicitly given.

To add another backend later, implement `call()` with the same signature and register it in BACKENDS.
"""
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field


class LLMError(RuntimeError):
    """kind: timeout | auth | budget | limit | invalid_output | not_installed | failed
    (limit = the Claude plan's usage limit is used up; retrying before it resets cannot help)"""

    def __init__(self, message, kind="failed", cost_usd=0.0):
        super().__init__(message)
        self.kind = kind
        self.cost_usd = cost_usd


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


BACKENDS = {"claude-code": ClaudeCode}


def make_backend(cfg):
    return BACKENDS[cfg["llm"]["backend"]](cfg)
