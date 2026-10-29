"""Supervisor: runs the crew, validates every step, and gets agents unstuck.

For each step: run the agent -> validate its output -> accept, or ask the supervisor model what to do:
  retry      run the same agent again with specific instructions
  rewind     go back to an earlier agent (e.g. the editor found a factual error -> research again)
  abort      stop: retrying cannot help
If the supervisor model itself is unavailable, it falls back to retrying with the raw problems as
instructions. Hard limits (attempts per step, attempts per run, dollars per run) always apply, and a
failed run notifies you with the reason. Nothing is ever queued without passing the Editor Review.
"""
import traceback

from .. import memory as memory_mod
from .. import platforms
from ..notify import notify
from . import team
from ..checks import STALE
from .base import AgentError, Feedback
from .credentials import CredentialsAgent
from .editor import EditorAgent
from .formatter import FormatterAgent
from .media import MediaAgent
from .publisher import PublisherAgent
from .research import ResearchAgent
from .script import ScriptWriter
from .topic import TopicAgent
from .blackboard import BlackboardAgent, ExplainerAgent
from .explainroo import ExplainrooAgent
from .frames import HyperFramesAgent, RemotionAgent, RemotionFramesAgent
from .hooks import HooksAgent
from .video import VideoAgent
from .video_review import VideoReviewAgent
from .voice import VoiceAgent
from .writer import WriterAgent

CREW = [CredentialsAgent(), TopicAgent(), ResearchAgent(), WriterAgent(), MediaAgent(), EditorAgent(),
        FormatterAgent(), PublisherAgent()]
# The YouTube crew: the same supervisor, topic scout, researchers, writer team (as the Script Writer) and Editor. The Editor
# reviews the SCRIPT, so the voice and the video are only made after it passes: nothing is spent on a script sent back.
YOUTUBE_CREW = [CredentialsAgent(), TopicAgent(), ResearchAgent(), ScriptWriter(), EditorAgent(), VoiceAgent(), VideoAgent(),
                VideoReviewAgent(), HooksAgent(), PublisherAgent()]
CREWS = {"linkedin": CREW, "youtube": YOUTUBE_CREW}
ORDER = [a.id for a in CREW]
FIXABLE = ["topic", "research", "writer", "voice", "text_frames", "data_frames", "media"]   # steps the supervisor may send work back to


def crew_for(platform, cfg=None, category=None):
    """The agents of one run. cfg: that app's view of the config (platforms.view); with the blackboard renderer the
    Blackboard Producer replaces the Video Producer."""
    crew = CREWS.get(platform) or CREW
    drawn = {"blackboard": BlackboardAgent, "explainer": ExplainerAgent, "explainroo": ExplainrooAgent, "remotion": RemotionAgent}.get(platforms.renderer_for(cfg, category)) if cfg else None
    if drawn:
        if drawn is RemotionAgent:   # three steps: the word scenes (HyperFrames), the data scenes (Remotion), then one joins them
            crew = [x for a in crew for x in ((HyperFramesAgent(), RemotionFramesAgent(), RemotionAgent()) if a.id == "media" else (a,))]
        else:
            crew = [drawn() if a.id == "media" else a for a in crew]
    return crew

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["retry", "rewind", "abort"]},
        "target": {"type": "string", "enum": FIXABLE + ["editor", "formatter", "publisher", "credentials"],
                   "description": "the step to run next (same step for retry)"},
        "instructions": {"type": "array", "items": {"type": "string"}, "maxItems": 6,
                         "description": "specific, actionable instructions for that agent"},
        "reason": {"type": "string"},
    },
    "required": ["action", "target", "instructions", "reason"],
    "additionalProperties": False,
}


MEDIA_WORDS = ("media", "poster", "image", "video", "visual", "slide", "animation", "diagram", "component")


def _about(problem, step):
    """Does an Editor point concern this step's work? (Editors label fixes 'Media: ...' or mention the poster.)"""
    p = problem.lower()
    if step in ("media", "text_frames", "data_frames"):
        return any(w in p for w in MEDIA_WORDS) or "red flag: poster_text_mismatch" in p
    return True


def clip(obj, n=1500):
    s = str(obj)
    return s if len(s) <= n else s[:n] + "...(cut)"


class Supervisor:
    id = "supervisor"
    title = "Supervisor"
    name = "Orion"
    role = "Orchestrates the crew, validates every step, and redirects agents that get stuck."

    def __init__(self, crew=None):
        self.crew = crew or CREW
        self.by_id = {a.id: a for a in self.crew}
        self.order = [a.id for a in self.crew]
        # work sent back to "the visuals" is drawn again from the first drawing step, not only joined again
        self.alias = {"media": "text_frames"} if "text_frames" in self.by_id else {}

    # ---------- the run ----------
    def run(self, ctx):
        run = ctx.run
        if ctx.memory is None:
            ctx.memory = memory_mod.RunMemory(run.dir)
        guidance = {s: self._fresh(ctx, s) for s in self.order}
        attempts = {s: 0 for s in self.order}
        total, i = 0, 0
        run.event("supervisor", "start", f"crew run for {ctx.day.isoformat()} - {ctx.cat['label']}",
                  {"category": ctx.category, "date": ctx.day.isoformat(), "dry_run": ctx.dry_run})
        while i < len(self.order):
            step = self.order[i]
            agent = self.by_id[step]
            if step not in ctx.outputs and not agent.applies(ctx):
                run.step(step, "skipped", summary="not needed for this category")
                run.event(step, "skipped", "not needed for this category")
                i += 1
                continue
            attempts[step] += 1
            total += 1
            run.step(step, "running", attempts=attempts[step])
            run.event(step, "started", f"{agent.title}: attempt {attempts[step]}",
                      {"guidance": guidance[step]} if guidance[step] else None)
            fatal = False
            try:
                out = agent.run(ctx, guidance[step])
                problems = agent.validate(ctx, out)
            except AgentError as e:
                out, problems, fatal = None, [str(e)], e.fatal
            except Exception as e:  # a bug or an unexpected failure: still logged and supervised
                out, problems = None, [f"{type(e).__name__}: {e}"]
                run.event(step, "exception", str(e), {"traceback": traceback.format_exc()[-2000:]}, level="error")
            if step == "editor" and out:
                self._record_editor(ctx, out, passed=not problems, problems=problems)
            if not problems:
                ctx.outputs[step] = out
                run.artifact(step, {k: v for k, v in out.items() if not k.startswith("_")})
                summary = agent.summary(out)
                run.step(step, "passed", summary=summary, errors=[])
                run.event(step, "passed", summary or "accepted")
                ctx.memory.add(step, "passed", attempt=attempts[step])
                i += 1
                continue
            run.step(step, "retrying", errors=problems)
            run.event(step, "rejected", f"{len(problems)} problem(s): {problems[0][:160]}", {"problems": problems},
                      level="warning")
            if out is not None:
                run.artifact(f"{step}.rejected.{attempts[step]}", {k: v for k, v in out.items()
                                                                   if not k.startswith("_")})
            reason = self._limit_reason(ctx, step, attempts, total, fatal)
            if reason:
                return self._fail(ctx, step, reason, problems)
            decision = self._diagnose(ctx, step, problems, out, attempts)
            run.note_intervention()
            run.event("supervisor", "decision", f"{decision['action']} -> {decision['target']}: {decision['reason']}",
                      decision)
            if decision["action"] == "abort":
                return self._fail(ctx, step, f"supervisor stopped the run: {decision['reason']}", problems)
            target = decision["target"]
            if target != step:
                target = self.alias.get(target, target)
            by = self._who(ctx, step, out)
            guidance[target] = self._feedback(ctx, target, decision["instructions"] or problems[:6], by, problems,
                                              attempts[step], exact=step == "editor")
            if out is not None and target == step:
                ctx.previous[step] = out
            if target != step:  # rewind: redo the target and everything after it
                i = self.order.index(target)
                for s in self.order[i:]:
                    if s in ctx.outputs:
                        ctx.previous[s] = ctx.outputs.pop(s)
                    if s != target:
                        guidance[s] = self._fresh(ctx, s)
                    run.step(s, "retrying" if s == target else "pending")
                if step == "editor" and target != step:
                    # every agent being redone between the target and the Editor gets the Editor's points for it:
                    # a rewind to the writer also redoes the poster, which must fix its own problems
                    for s in self.order[self.order.index(target) + 1:self.order.index(step)]:
                        if s in FIXABLE:
                            mine = [p for p in problems if _about(p, s)]
                            if mine:
                                guidance[s] = self._feedback(ctx, s, mine[:6], by, mine, attempts[step], exact=True)
        run.finish("succeeded", self._result_text(ctx))
        self._remember(ctx)
        self._review_team(ctx)
        return {"ok": True, "post": ctx.outputs.get("publisher"), "cost_usd": run.cost}

    # ---------- feedback and memory ----------
    def _who(self, ctx, step, out=None):
        """Who sent the work back, for the agent that has to fix it: 'Quinn (Editor Review)'."""
        a = self.by_id[step]
        names = [m.get("name") for m in (out or {}).get("team", []) if m.get("name")] if isinstance(out, dict) else []
        if step == "writer" and isinstance(out, dict) and out.get("author_name"):
            names = [out["author_name"]]
        name = ", ".join(names) or (a.name if a.name and "team" not in a.name else "")
        return f"{name} ({a.title})" if name else a.title

    def _fresh(self, ctx, step):
        """First-attempt feedback: what this step got wrong earlier in the run and in earlier runs."""
        return Feedback(before=ctx.memory.reasons(step) if ctx.memory else [], past=self._past(ctx, step))

    def _past(self, ctx, step):
        try:
            return memory_mod.recall(ctx.ws, step)
        except Exception:
            return []

    def _feedback(self, ctx, step, instructions, by, why, attempt, exact=False):
        """Send work back to `step` with the reasons it failed, and keep them in the run's working memory."""
        fb = Feedback(instructions, by=by, why=why[:12], before=ctx.memory.reasons(step), past=self._past(ctx, step),
                      exact=exact)
        ctx.memory.add(step, "sent_back", by=by, why=why, instructions=instructions, attempt=attempt)
        return fb

    def _remember(self, ctx):
        """Only after a run whose post passed the Editor, so only fixes that worked are kept."""
        try:
            n = memory_mod.remember(ctx.ws, ctx.memory, ctx.run.status["run_id"])
            if n:
                ctx.run.event("supervisor", "memory", f"remembered {n} fixed problem(s) for future runs")
        except Exception as e:  # memory must never break a run
            ctx.run.event("supervisor", "memory_error", str(e)[:200], level="warning")

    # ---------- the team ----------
    def _record_editor(self, ctx, out, passed, problems):
        """The Editor's verdict counts for the writer whose draft it judged, and for the researchers when the
        Editor blames the facts."""
        run_id = ctx.run.status["run_id"]
        w = ctx.outputs.get("writer") or {}
        try:
            if w.get("author"):
                team.record(ctx.ws, w["author"], run_id, good=passed, score=out.get("overall"), editor=passed,
                            problems=[] if passed else problems)
            if not passed and out.get("fix_owner") == "research":
                for m in (ctx.outputs.get("research") or {}).get("team", []):
                    team.record(ctx.ws, m["member"], run_id, good=False, editor=False, problems=problems)
        except Exception as e:  # the roster must never break a run
            ctx.run.event("supervisor", "team_error", str(e)[:200], level="warning")

    def _review_team(self, ctx):
        """After every run: replace members whose recent work is consistently bad."""
        try:
            for fired, hired in team.review(ctx.ws, ctx.cfg, llm=ctx.llm):
                ctx.run.event("supervisor", "team", f"{fired['name']} ({fired['role']}) was replaced by "
                                                    f"{hired['name']} after consistently bad output",
                              {"fired": fired["id"], "hired": hired["id"]}, level="warning")
        except Exception as e:
            ctx.run.event("supervisor", "team_error", str(e)[:200], level="warning")

    # ---------- decisions ----------
    def _limit_reason(self, ctx, step, attempts, total, fatal):
        pl = ctx.cfg["pipeline"]
        if fatal:
            return "this cannot be fixed by retrying"
        if attempts[step] >= pl["max_attempts_per_step"]:
            return f"{self.by_id[step].title} failed {attempts[step]} times"
        if total >= pl["max_total_attempts"]:
            return f"the run used all {pl['max_total_attempts']} attempts"
        if ctx.run.cost >= pl["max_run_budget_usd"]:
            return f"the run reached its ${pl['max_run_budget_usd']:.2f} budget"
        return None

    def _diagnose(self, ctx, step, problems, out, attempts):
        """Ask the supervisor model what to do. Deterministic fallback when it is unavailable."""
        default_target = step
        if step == "editor" and out:
            default_target = out.get("fix_owner") if out.get("fix_owner") in FIXABLE else "writer"
        if step == "formatter":
            default_target = "writer"
        if step == "research" and any(p.startswith(STALE) for p in problems):
            # research cannot make an old story new: always go back to the Topic Scout
            return {"action": "rewind", "target": "topic", "reason": "every source is older than allowed",
                    "instructions": [p for p in problems if p.startswith(STALE)][:1]
                    + ["pick a story whose primary source was published inside the window"]}
        fallback = {"action": "retry" if default_target == step else "rewind", "target": default_target,
                    "instructions": problems[:6], "reason": "fixing the reported problems"}
        if step == "editor" and out:
            # the Editor already wrote exact, minimal edits and named who must make them: pass them on word for
            # word. Re-wording them (or adding to them) is what made revisions drift away from what was asked.
            return {"action": "rewind", "target": default_target, "instructions": out.get("fixes") or problems[:6],
                    "reason": f"Editor scored {out.get('overall')}; {default_target} applies the Editor's fixes as written"}
        if step in ("credentials", "publisher"):
            return fallback
        upstream = {s: clip({k: v for k, v in (ctx.outputs.get(s) or {}).items() if not k.startswith("_")}, 900)
                    for s in self.order if s in ctx.outputs and s not in ("credentials",)}
        prompt = (f"Category: {ctx.cat['label']} - {ctx.cat['brief']}\n"
                  f"Failed step: {step} ({self.by_id[step].role})\nAttempts so far: {attempts}\n"
                  f"Problems found by validation:\n" + "\n".join(f"- {p}" for p in problems) +
                  self._history(ctx) +
                  f"\n\nThe failed output:\n{clip(out, 2500)}\n\nAccepted outputs so far:\n" +
                  "\n".join(f"[{k}] {v}" for k, v in upstream.items()) +
                  f"\n\nSteps you may send work to: {[s for s in FIXABLE if s in self.order and self.order.index(s) <= self.order.index(step)]}"
                  f" (or {step} itself).")
        try:
            res = ctx.llm.call("supervisor", self._system(ctx), prompt, SCHEMA, cwd=str(ctx.run.dir))
            ctx.run.add_cost("supervisor", res.cost_usd)
            d = res.data
        except Exception as e:
            ctx.run.event("supervisor", "fallback", f"supervisor model unavailable ({str(e)[:120]}); "
                                                    f"retrying with the raw problems", level="warning")
            return fallback
        allowed = [s for s in self.order if self.order.index(s) <= self.order.index(step)]
        if d.get("target") not in allowed:
            d["target"] = default_target
        if d["action"] == "retry":
            d["target"] = step
        elif d["action"] == "rewind" and d["target"] == step:
            d["action"] = "retry"
        if d["action"] == "retry" and default_target != step:
            # a reviewer/formatter that produced a valid verdict cannot fix the draft by itself: send it back
            d.update(action="rewind", target=default_target)
        return d

    def _history(self, ctx):
        rows = [f"- {e['step']} sent back (by {e['by']}): {'; '.join(e['why'][:2])[:300]}"
                for e in (ctx.memory.entries if ctx.memory else []) if e["kind"] == "sent_back"]
        return ("\n\nEarlier in this run (do not repeat an instruction that did not work):\n" + "\n".join(rows[-8:])
                if rows else "")

    def _system(self, ctx):
        from .base import PROMPTS
        override = ctx.ws.root / "prompts" / "supervisor.md"
        return (override if override.exists() else PROMPTS / "supervisor.md").read_text()

    # ---------- endings ----------
    def _fail(self, ctx, step, reason, problems):
        ctx.run.step(step, "failed", errors=problems)
        for s in self.order[self.order.index(step) + 1:]:
            if ctx.run.status["steps"][s]["state"] in ("pending", "retrying"):
                ctx.run.step(s, "blocked")
        msg = f"{reason}. Last problems: " + "; ".join(problems[:3])
        ctx.run.finish("failed", msg)
        self._review_team(ctx)  # no long-term memory from a failed run: its "fixes" did not get a post approved
        a = self.by_id[step]
        notify(ctx.ws, f"No post for {ctx.day.isoformat()}", f"The crew stopped at {getattr(a, 'name', '') or a.title} "
               f"({a.title}): {reason}.", level="error", key=f"run-failed-{ctx.day.isoformat()}",
               action={"label": "See the run", "tab": "workflow"}, quiet_hours=1,
               details={"rows": [("Post date", ctx.day.strftime("%a %d %b %Y")),
                                 ("Kind of post", ctx.cat.get("label", ctx.category)),
                                 ("Topic", (ctx.outputs.get("topic") or {}).get("topic", "not chosen yet")),
                                 ("Stopped at", f"{getattr(a, 'name', '') or a.title}, {a.title}"),
                                 ("Why", reason)]
                        + [(f"Problem {i}", p[:300]) for i, p in enumerate(problems[:3], 1)]
                        + [("Tries", sum(x.get("attempts", 0) for x in ctx.run.status["steps"].values())),
                           ("Cost", f"${ctx.run.cost:.2f} at API prices"), ("Run", ctx.run.status["run_id"]),
                           ("What to do", "Open the run to see every attempt, then start a new run for this date "
                                          "from the Overview, or plan a different topic.")]})
        return {"ok": False, "failed_step": step, "reason": reason, "problems": problems, "cost_usd": ctx.run.cost}

    def _result_text(self, ctx):
        p = ctx.outputs.get("publisher") or {}
        return f"'{ctx.outputs['topic']['topic']}' {p.get('status', 'done')} (${ctx.run.cost:.3f})"
