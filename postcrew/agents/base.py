"""What every agent shares.

An agent does ONE job: `run(ctx, guidance)` returns a JSON-able dict, and `validate(ctx, output)` returns a
list of problems (empty = accepted). The supervisor calls both, logs everything, and decides what happens
when validation fails. `guidance` is the list of corrective instructions the supervisor gives on a retry.

Prompts live in postcrew/prompts/<agent>.md. A user can override any of them by putting a file with the
same name in workspace/prompts/.
"""
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..checks import fetch_text
from ..llm import LLMError

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


class AgentError(RuntimeError):
    """A failure inside an agent. `fatal` = retrying cannot help (missing tool, nothing left to post...)."""

    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal


@dataclass
class RunContext:
    ws: object
    cfg: dict
    day: date
    category: str
    run: object                       # RunLog
    llm: object                       # backend with .call()
    outputs: dict = field(default_factory=dict)
    fetch: object = fetch_text
    dry_run: bool = False
    page_cache: dict = field(default_factory=dict)   # pages the researcher downloaded, url -> text
    previous: dict = field(default_factory=dict)     # an agent's last output before it was sent back

    @property
    def cat(self):
        return self.cfg["categories"][self.category]

    @property
    def profile(self):
        return self.cfg["profile"]

    def recent(self, n=20):
        return self.ws.recent_posts(n)


class Agent:
    id = "agent"
    title = "Agent"
    role = ""
    uses_llm = True

    def applies(self, ctx):
        """False = this step is skipped for this kind of post (shown as 'skipped' in the graph)."""
        return True

    def run(self, ctx, guidance):
        raise NotImplementedError

    def validate(self, ctx, out):
        return []

    def summary(self, out):
        return ""

    # ---------- helpers ----------
    def prompt(self, ctx, name=None, **values):
        name = name or self.id
        override = Path(ctx.ws.root) / "prompts" / f"{name}.md"
        text = (override if override.exists() else PROMPTS / f"{name}.md").read_text()
        p = ctx.profile
        base = {"audience": p.get("audience", ""), "voice": p.get("voice", ""),
                "about": "\n".join(f"- {a}" for a in p.get("about", [])) or "- (nothing listed)",
                "name": p.get("name", "") or "the account owner"}
        base.update(values)
        for k, v in base.items():
            text = text.replace("{{" + k + "}}", str(v))
        return text

    def ask(self, ctx, system, prompt, schema, tools=()):
        try:
            res = ctx.llm.call(self.id, system, prompt, schema, tools=tools, cwd=str(ctx.run.dir))
        except LLMError as e:
            ctx.run.add_cost(self.id, e.cost_usd)
            raise AgentError(f"LLM {e.kind}: {e}", fatal=e.kind in ("not_installed", "auth"))
        ctx.run.add_cost(self.id, res.cost_usd)
        ctx.run.event(self.id, "llm", f"{res.model or 'model'} answered in {res.duration_s}s "
                                      f"(${res.cost_usd:.4f}, {res.turns} turns)",
                      {"cost_usd": res.cost_usd, "model": res.model, "turns": res.turns})
        return res.data


def guidance_block(guidance):
    if not guidance:
        return ""
    return ("\n\nA SUPERVISOR REVIEWED YOUR LAST ATTEMPT. Fix every point:\n" +
            "\n".join(f"- {g}" for g in guidance))


def recent_block(ctx, n=15):
    rows = [f"- {p.get('date', '')} [{p.get('category', '')}] {p.get('topic', '')}" for p in ctx.recent(n)]
    return "\n".join(rows) or "- (no posts yet)"
