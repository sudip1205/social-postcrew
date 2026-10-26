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
    memory: object = None                             # RunMemory: what went wrong earlier in this run
    reviews: list = field(default_factory=list)       # the Editor's earlier rounds in this run
    platform: str = "linkedin"                        # the app this post is for; cfg is that app's view of the config
    options: dict = field(default_factory=dict)       # one-off overrides for this run (e.g. a video's format and length)

    @property
    def cat(self):
        return self.cfg["categories"][self.category]

    @property
    def profile(self):
        return self.cfg["profile"]

    @property
    def video(self):
        """The kind of video this run makes (YouTube): format, target_seconds, max_words."""
        from .. import platforms
        from .planner import planned_for
        return platforms.video_spec(self.cfg, self.cat, planned_for(self.ws, self.day, self.category, self.platform),
                                    self.options)

    def recent(self, n=20):
        return self.ws.recent_posts(n, self.platform)


class Agent:
    id = "agent"
    title = "Agent"
    name = ""
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
    @staticmethod
    def _prompt_file(ctx, name):
        """Your own prompts/<app>/<name>.md, the built-in one for that app, your prompts/<name>.md, the built-in one."""
        root = Path(ctx.ws.root) / "prompts"
        platform = getattr(ctx, "platform", "linkedin")
        for path in ((root / platform / f"{name}.md", PROMPTS / platform / f"{name}.md") if platform != "linkedin" else ()) \
                + (root / f"{name}.md", PROMPTS / f"{name}.md"):
            if path.exists():
                return path
        raise FileNotFoundError(f"no prompt {name}.md")

    def prompt(self, ctx, name=None, **values):
        name = name or self.id
        text = self._prompt_file(ctx, name).read_text()
        p = ctx.profile
        base = {"audience": p.get("audience", ""), "voice": p.get("voice", ""),
                "about": "\n".join(f"- {a}" for a in p.get("about", [])) or "- (nothing listed)",
                "name": p.get("name", "") or "the account owner"}
        if "{{rubric}}" in text:  # the scoring guide the Writer writes to and the Editor scores by
            base["rubric"] = self._prompt_file(ctx, "rubric").read_text().strip()
        if "{{brief_rules}}" in text:  # the owner's per-post brief, as the reviewers must judge it
            from .. import brief as briefmod
            base["brief_rules"] = briefmod.editor_rules(briefmod.of(ctx))
        base.update(values)
        for k, v in base.items():
            text = text.replace("{{" + k + "}}", str(v))
        return text

    def ask(self, ctx, system, prompt, schema, tools=(), member=None, agent_id=None):
        """member: a team member dict (their model, if any, overrides the agent's). agent_id: settings to use."""
        aid = agent_id or self.id
        kw = {"member": member["id"]} if member else {}
        if member and member.get("model"):
            kw["model"] = member["model"]
        try:
            res = ctx.llm.call(aid, system, prompt, schema, tools=tools, cwd=str(ctx.run.dir), **kw)
        except LLMError as e:
            ctx.run.add_cost(self.id, e.cost_usd)
            raise AgentError(f"LLM {e.kind}: {e}", fatal=e.kind in ("not_installed", "auth", "limit"))
        ctx.run.add_cost(self.id, res.cost_usd)
        ctx.run.add_tokens(self.id, res.tokens)
        who = f"{member['name']}: " if member else ""
        ctx.run.event(self.id, "llm", f"{who}{res.model or 'model'} answered in {res.duration_s}s "
                                      f"(${res.cost_usd:.4f}, {res.turns} turns)",
                      {"cost_usd": res.cost_usd, "model": res.model, "turns": res.turns, "member": kw.get("member")})
        return res.data


class Feedback(list):
    """The Supervisor's instructions for an agent (the list itself), plus why its work was sent back:
    by     who rejected it ("Quinn, the Editor")
    why    the problems found in this attempt, word for word
    before reasons the same work was sent back earlier in this run (working memory)
    past   problems this step had in earlier runs and what fixed them (long-term memory)
    exact  the instructions are a reviewer's own minimal edits, to apply word for word
    An empty Feedback is falsy, so a first attempt with only `past` still counts as "no guidance"."""

    def __init__(self, instructions=(), by="", why=(), before=(), past=(), exact=False):
        super().__init__(instructions)
        self.by, self.why, self.before, self.past, self.exact = by, list(why), list(before), list(past), exact


def guidance_block(guidance):
    by, instructions = getattr(guidance, "by", ""), list(guidance or [])
    why = [w for w in getattr(guidance, "why", []) if w not in instructions]  # show each point once
    before = [b for b in getattr(guidance, "before", []) if b not in why and b not in instructions]
    past = getattr(guidance, "past", [])
    out = ""
    if past:
        out += ("\n\nCREW MEMORY - problems this step had in earlier runs and what fixed them (avoid them from the "
                "start):\n" + "\n".join(f"- {p['problem']}" + (f" -> fixed by: {'; '.join(p['fix'])}" if p.get("fix") else "")
                                         for p in past))
    if not (instructions or why or before):
        return out
    if why or instructions:
        out += f"\n\nYOUR LAST ATTEMPT WAS SENT BACK{' by ' + by if by else ''}."
    if why:
        out += "\nWHY IT FAILED:\n" + "\n".join(f"- {w}" for w in why)
    if before:
        out += ("\n\nALSO SENT BACK EARLIER IN THIS RUN FOR (already fixed once - do not bring these back):\n"
                + "\n".join(f"- {b}" for b in before[-4:]))
    if instructions and getattr(guidance, "exact", False):
        out += ("\n\nTHE REVIEWER'S FIXES - apply each one exactly as written (they are minimal edits; use the "
                "replacement wording given). Change nothing else: every sentence no fix mentions stays word for word.\n"
                + "\n".join(f"- {g}" for g in instructions))
    elif instructions:
        out += ("\n\nA SUPERVISOR REVIEWED YOUR LAST ATTEMPT. Fix every point:\n" +
                "\n".join(f"- {g}" for g in instructions))
    return out


def recent_block(ctx, n=15):
    def hook(p):
        line = next((s.strip() for s in (p.get("text") or "").splitlines() if s.strip()), "")
        return f' - "{line[:110]}"' if line else ""
    rows = [f"- {p.get('date', '')} [{p.get('category') or '?'}] {p.get('topic', '')}{hook(p)}" for p in ctx.recent(n)]
    return "\n".join(rows) or "- (no posts yet)"
