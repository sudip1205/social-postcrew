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
    flags: dict = field(default_factory=dict)         # things an agent did once in this run (a retry of the step must not repeat them)
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
        if "{{length_note}}" in text:   # YouTube Editor: how much room a Short has left, so its fixes swap words instead of adding them
            base["length_note"] = length_note(ctx)
        if "{{script_style}}" in text:   # YouTube: the script style learned from your approved reference videos (Motion Studio)
            from ..motion.library import Library
            try:
                st = Library(ctx.ws).script_brief()
            except Exception:
                st = ""
            base["script_style"] = (f"\n{st}\nFollow this style in HOW you write (hook, rhythm, sentences, devices), inside the required "
                                    f"parts and rules below, which always win. Never copy a reference's words.\n") if st else ""
        if "{{brief_rules}}" in text:  # the owner's per-post brief, as the reviewers must judge it
            from .. import brief as briefmod
            base["brief_rules"] = briefmod.editor_rules(briefmod.of(ctx))
        try:   # YouTube: the owner's required closing line (ctx.video exists only for a video run)
            base["outro"] = ctx.video.get("outro") or "(none)"
        except Exception:
            base["outro"] = "(none)"
        base.update(values)
        for k, v in base.items():
            text = text.replace("{{" + k + "}}", str(v))
        return text

    @staticmethod
    def _record_block(ctx, agent_id, member=None):
        """The agent's past work as the owner judged it (rewards.py): its points, what was vetoed and why, and for the agents that shape a
        video, the outline of the video to follow. Never breaks a call."""
        try:
            from .. import rewards
            fmt = ctx.video.get("format", "short") if getattr(ctx, "platform", "linkedin") == "youtube" else "short"
            block = rewards.prompt_block(ctx.ws, agent_id, getattr(ctx, "platform", "linkedin"), fmt, getattr(ctx, "category", None),
                                         member["id"] if member else None)
            return f"\n\n{block}" if block else ""
        except Exception:
            return ""

    def ask(self, ctx, system, prompt, schema, tools=(), member=None, agent_id=None, images=()):
        """member: a team member dict (their model, if any, overrides the agent's). agent_id: settings to use.
        images: picture files the model looks at (the Quality Director's frames)."""
        aid = agent_id or self.id
        kw = {"member": member["id"]} if member else {}
        if images:
            kw["images"] = [str(p) for p in images]
        if member and member.get("model"):
            kw["model"] = member["model"]
        system += self._record_block(ctx, aid, member) + owner_plan_block(ctx, aid)
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


OWNER_PLAN_READERS = ("research", "writer", "editor", "reviewer", "direction", "graphics", "media", "quality", "video_review", "explainroo")


def owner_plan_block(ctx, agent_id):
    """A plan you wrote yourself (Manual run > Add your own plan): your topic, details and how you want it made, for every agent that
    shapes the work. Your directions win over the defaults, never over the hard rules (length, facts, the checks)."""
    try:
        p = (ctx.outputs.get("topic") or {}).get("owner_plan")
    except Exception:
        return ""
    if not p or agent_id not in OWNER_PLAN_READERS:
        return ""
    lines = ["\n\nTHE OWNER WROTE THIS PLAN THEMSELVES. Follow it: where it differs from the usual way, the owner's plan wins (the hard "
             "rules, length limits and fact checks still apply). Never contradict it, and judge the work by it.",
             f"Topic: {p.get('title', '')}"]
    if p.get("context"):
        lines.append(f"What it must cover (the owner's details):\n{p['context']}")
    if p.get("how"):
        lines.append(f"How the owner wants it made (style, structure, pictures, examples, tone):\n{p['how']}")
    if p.get("references"):
        lines.append("The owner's references (read them if you can browse): " + ", ".join(p["references"]))
    return "\n".join(lines)


def length_note(ctx):
    """For the Editor of a Short: the words now, the most a Short holds, and the rule for fixes when there is little room."""
    try:
        if ctx.video.get("format") != "short":
            return ""
    except Exception:
        return ""
    from ..checks import short_max_words
    words = len(((ctx.outputs.get("writer") or {}).get("text") or "").split())
    cap = short_max_words()
    room = cap - words
    if room >= 60:
        return f"- WORD ROOM: this Short has {words} words of narration; it may have up to {cap}. Your fixes may add words."
    return (f"- WORD ROOM: this Short has {words} words of narration and may have at most {cap}: only {max(room, 0)} words of room. "
            f"Every fix that adds words must also say exactly which sentence to cut or shorten so the total does not grow beyond {cap} "
            f"(\"replace X with Y\" of about the same length, not \"add\"). A fix that would push the script over the limit is sent back "
            f"by the length check and wastes a round.")


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
