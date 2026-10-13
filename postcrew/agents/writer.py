"""Writer agent: turns the topic and the verified research into the post text.

A team of writers (Settings > team.writer) drafts in parallel, each in their own style. Every draft goes
through the automatic checks, then a pre-review that scores it the way the Editor will. The best draft gets
one polish round from its author with the pre-review's fixes, and only the best version goes on to the
Editor. Each member's result is recorded on the roster (see team.py).
"""
import json
from concurrent.futures import ThreadPoolExecutor

from ..checks import link_problems, number_problems, repeat_problem, text_problems
from . import team
from .base import Agent, AgentError, Feedback, guidance_block, recent_block
from .editor import CRITERIA, RED_FLAGS, SCHEMA as REVIEW_SCHEMA, review_material

SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "The full post. Plain text, \\n for new lines, hashtags on the last line"},
        "first_comment": {"type": "string", "description": "The primary source URL, or empty"},
    },
    "required": ["text", "first_comment"],
    "additionalProperties": False,
}


def research_block(research):
    if not research:
        return "No research for this category: use only well-established, general knowledge."
    if research.get("reference"):
        return ("TRUSTED REFERENCE FACTS (use these, add no others):\n" +
                json.dumps(research["reference"], ensure_ascii=False, indent=1))
    lines = ["VERIFIED SOURCES (the only facts, numbers and links you may use):"]
    for s in research.get("verified", []):
        if s["verified"]:
            lines.append(f"- {s['url']} ({s.get('title', '')}, published {s.get('published') or 'unknown'})")
            lines += [f'    quote: "{e}"' for e in s["found"]]
    if research.get("notes"):
        lines.append(f"Researcher notes: {research['notes']}")
    return "\n".join(lines)


def revision_block(ctx, guidance, prev=None):
    prev = prev or ctx.previous.get("writer")
    if not (guidance and prev):
        return ""
    return ("\n\nYOUR PREVIOUS DRAFT was sent back. REVISE it: keep what works and change only what the points "
            "below require. Do not add new claims while fixing.\n<previous_draft>\n" + prev["text"] + "\n</previous_draft>")


class WriterAgent(Agent):
    id = "writer"
    title = "Writer"
    name = "Writing team"
    role = "Writes the post from verified facts only, in the owner's voice."

    def run(self, ctx, guidance):
        tcfg, pl = ctx.cfg["team"], ctx.cfg["pipeline"]
        members = team.active(ctx.ws, "writer", tcfg["writer"])
        with ThreadPoolExecutor(max_workers=len(members)) as pool:
            drafts = list(pool.map(lambda m: self._safe_draft(ctx, guidance, m), members))
        fatal = next((d for d in drafts if isinstance(d, AgentError) and d.fatal), None)
        if fatal:
            raise fatal
        cands = []
        for m, d in zip(members, drafts):
            if isinstance(d, Exception):
                cands.append({"member": m, "out": None, "problems": [str(d)], "review": None})
                continue
            cands.append({"member": m, "out": d, "problems": self.validate(ctx, d), "review": None})
        clean = [c for c in cands if c["out"] and not c["problems"]]
        if tcfg.get("pre_review") and clean:
            with ThreadPoolExecutor(max_workers=len(clean)) as pool:
                for c, rv in zip(clean, pool.map(lambda c: self._pre_review(ctx, c["out"]), clean)):
                    c["review"] = rv
        best = self._pick(cands, pl)
        if best and tcfg.get("pre_review") and best["review"] and not self._passes(best["review"], pl,
                                                                                tcfg.get("pre_review_margin", 5)):
            best = self._polish(ctx, best, guidance, pl) or best
        for c in cands:
            rv = c["review"]
            good = bool(c["out"]) and not c["problems"] and (rv is None or self._passes(rv, pl))
            team.record(ctx.ws, c["member"]["id"], ctx.run.status["run_id"], good=good,
                        score=rv["overall"] if rv else None, chosen=c is best,
                        problems=c["problems"] + ((rv.get("fixes", []) + [f"red flag: {f}" for f in rv["red_flags"]])
                                                  if rv and not self._passes(rv, pl) else []))
            ctx.run.event(self.id, "member", f"{c['member']['name']}: " + (
                f"{len(c['problems'])} problem(s): {c['problems'][0][:120]}" if c["problems"] else
                f"pre-review {rv['overall']}{' (flags: ' + ', '.join(rv['red_flags']) + ')' if rv['red_flags'] else ''}"
                if rv else "passed the checks") + (" - chosen" if c is best else ""),
                {"member": c["member"]["id"], "problems": c["problems"], "review": rv},
                level="warning" if c["problems"] else "info")
        if not best:
            raise AgentError("; ".join(c["problems"][0] for c in cands if c["problems"])[:500])
        out = dict(best["out"], author=best["member"]["id"], author_name=best["member"]["name"],
                   pre_review=best["review"],
                   team=[{"member": c["member"]["id"], "name": c["member"]["name"], "problems": c["problems"][:4],
                          "score": (c["review"] or {}).get("overall"), "flags": (c["review"] or {}).get("red_flags", []),
                          "chosen": c is best} for c in cands])
        return out

    @staticmethod
    def _passes(rv, pl, margin=0):
        """margin: the pre-review is one read and the Editor keeps the worst of several, so the best draft is
        polished until it clears the bar by this much."""
        return (rv["overall"] >= pl["min_overall"] + margin and not rv["red_flags"]
                and min(rv["scores"].get(k, 0) for k in CRITERIA) >= pl["min_subscore"])

    def _pick(self, cands, pl):
        """Clean drafts beat drafts with problems; then passing the pre-review; then the higher score;
        among drafts with problems, the fewest problems (validation then reports them)."""
        usable = [c for c in cands if c["out"]]
        if not usable:
            return None
        return max(usable, key=lambda c: (not c["problems"], bool(c["review"]) and self._passes(c["review"], pl),
                                          (c["review"] or {}).get("overall", 0) - 15 * len((c["review"] or {}).get("red_flags", [])),
                                          -len(c["problems"])))

    def _pre_review(self, ctx, draft):
        try:
            return self.ask(ctx, self.prompt(ctx, "editor", red_flags=", ".join(RED_FLAGS)),
                            review_material(ctx, draft), REVIEW_SCHEMA, agent_id="reviewer")
        except AgentError as e:
            if e.fatal:
                raise
            ctx.run.event(self.id, "pre_review_failed", str(e)[:200], level="warning")
            return None

    def _polish(self, ctx, best, guidance, pl):
        """One revision by the best draft's author with the pre-review's fixes; kept only if it scores higher."""
        rv = best["review"]
        notes = rv.get("fixes", []) + [f"remove the red flag: {f}" for f in rv["red_flags"]] + [rv.get("reasons", "")]
        try:
            fb = Feedback([n for n in notes if n][:6] + list(guidance), by="Iris (Pre-reviewer)",
                          why=[n for n in notes if n][:6], before=getattr(guidance, "why", []) + getattr(guidance, "before", []),
                          past=getattr(guidance, "past", []))
            d = self._draft(ctx, fb, best["member"], prev=best["out"])
        except AgentError as e:
            if e.fatal:
                raise
            return None
        problems = self.validate(ctx, d)
        if problems:
            ctx.run.event(self.id, "polish", f"{best['member']['name']}'s polished draft failed the checks; keeping "
                                             f"the original: {problems[0][:120]}", level="warning")
            return None
        rv2 = self._pre_review(ctx, d)
        if not rv2 or rv2["overall"] - 15 * len(rv2["red_flags"]) <= rv["overall"] - 15 * len(rv["red_flags"]):
            ctx.run.event(self.id, "polish", f"polish did not raise the score ({rv['overall']} -> "
                                             f"{rv2['overall'] if rv2 else '?'}); keeping the original")
            return None
        ctx.run.event(self.id, "polish", f"{best['member']['name']} polished the draft: {rv['overall']} -> {rv2['overall']}")
        return dict(best, out=d, review=rv2)

    def _safe_draft(self, ctx, guidance, member):
        try:
            return self._draft(ctx, guidance, member)
        except AgentError as e:
            return e
        except Exception as e:
            return AgentError(f"{type(e).__name__}: {e}")

    def _draft(self, ctx, guidance, member, prev=None):
        topic = ctx.outputs["topic"]
        system = (self.prompt(ctx, min_chars=ctx.cat["min_chars"], max_chars=ctx.cat["max_chars"])
                  + team.persona_block(ctx.ws, member))
        prompt = (f"Category: {ctx.cat['label']}\nWhat this category needs: {ctx.cat['brief']}\n"
                  f"Length: {ctx.cat['min_chars']}-{ctx.cat['max_chars']} characters.\n"
                  f"Topic: {topic['topic']}\nAngle: {topic['angle']}\n\n"
                  + research_block(ctx.outputs.get("research"))
                  + ("\n\nPOSTS OF THE WEEK (draw the recap only from these):\n" +
                     json.dumps(topic["week_posts"], ensure_ascii=False, indent=1) if topic.get("week_posts") else "")
                  + f"\n\nRecent posts (match the voice, do not repeat structure):\n{recent_block(ctx, 8)}"
                  + revision_block(ctx, guidance, prev)
                  + guidance_block(guidance))
        return self.ask(ctx, system, prompt, SCHEMA, member=member)

    def validate(self, ctx, out):
        text, fc = out.get("text") or "", out.get("first_comment") or ""
        research = ctx.outputs.get("research") or {}
        verified = [dict(s, page=research.get("_pages", {}).get(s["url"], "")) for s in research.get("verified", [])]
        problems = text_problems(text, ctx.cat, ctx.profile, fc)
        problems += link_problems(text, fc, verified)
        if ctx.cat.get("fact_check"):
            problems += number_problems(text, "", verified)
        dup = repeat_problem("", text, ctx.recent(60))
        if dup:
            problems.append(dup)
        if ctx.cat.get("research") == "required" and not fc:
            problems.append("first_comment must be the primary source URL")
        return problems

    def summary(self, out):
        t = out.get("text", "")
        who = f"by {out['author_name']}" if out.get("author_name") else ""
        if len(out.get("team", [])) > 1:
            who += f" (best of {len(out['team'])})"
        if out.get("pre_review"):
            who += f", pre-review {out['pre_review']['overall']}"
        return f"{len(t)} chars {who}: {t.splitlines()[0][:60] if t else ''}"
