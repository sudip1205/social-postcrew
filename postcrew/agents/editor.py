"""Editor Review agent: a strict reviewer that scores the post several times and keeps the worst result.

Passes only when the lowest overall score >= pipeline.min_overall, no sub-score < pipeline.min_subscore,
and no run raised a red flag. When it fails it says which agent should fix it (fix_owner), so the
supervisor can send the work back to the right step.
"""
import json

from .base import Agent, AgentError

CRITERIA = ["accuracy", "clarity", "hook", "value", "tone", "format"]
RED_FLAGS = ["unsupported_claim", "factual_error", "code_error", "placeholder", "misleading_headline",
             "too_promotional", "political_or_offensive", "confidential_or_employer_reference",
             "invented_experience", "poster_text_mismatch", "other"]
OWNERS = ["writer", "media", "research", "topic"]
SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {"type": "object", "properties": {k: {"type": "integer", "minimum": 0, "maximum": 100}
                                                    for k in CRITERIA}, "required": CRITERIA,
                   "additionalProperties": False},
        "overall": {"type": "integer", "minimum": 0, "maximum": 100},
        "red_flags": {"type": "array", "items": {"type": "string", "enum": RED_FLAGS}},
        "reasons": {"type": "string"},
        "fixes": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "required": ["criterion", "fix"], "additionalProperties": False,
            "properties": {"criterion": {"type": "string", "enum": CRITERIA + ["red_flag"]},
                           "fix": {"type": "string", "description": "an exact, minimal edit with the replacement wording"}}}},
        "fix_owner": {"type": "string", "enum": OWNERS, "description": "which agent must change something"},
    },
    "required": ["scores", "overall", "red_flags", "reasons", "fixes", "fix_owner"],
    "additionalProperties": False,
}


def review_material(ctx, draft=None):
    """draft: review this writer output instead of the accepted one (the writer team's pre-review)."""
    w, m, r = draft or ctx.outputs["writer"], ctx.outputs.get("media") or {}, ctx.outputs.get("research") or {}
    parts = [f"CATEGORY: {ctx.cat['label']} (length target {ctx.cat['min_chars']}-{ctx.cat['max_chars']} chars)",
             f"WHAT THIS CATEGORY NEEDS: {ctx.cat['brief']}", "", "<draft>", "POST TEXT:", w["text"], "",
             f"FIRST COMMENT: {w.get('first_comment') or '(none)'}", "",
             "TEXT SHOWN ON THE IMAGE/VIDEO:", m.get("shown_text") or "(no media)", "</draft>"]
    if r.get("reference"):
        parts += ["", "<reference_facts> (trusted, built in)", json.dumps(r["reference"], ensure_ascii=False, indent=1),
                  "</reference_facts>"]
    elif r.get("verified"):
        parts += ["", "<sources> (re-fetched; 'verified' = the quotes were found on the live page)"]
        for s in r["verified"]:
            parts.append(f"- {s['url']} | verified: {s['verified']} | published: {s.get('published') or 'unknown'}")
            parts += [f'  quote: "{e[:600]}"' for e in s.get("found", [])]
        parts.append("</sources>")
    elif ctx.cat.get("research") == "required":
        parts += ["", "<sources>none</sources>"]
    parts += ["", "<about_the_owner> (the only personal facts the post may claim)",
              "\n".join(ctx.profile.get("about", [])) or "(none)", "</about_the_owner>"]
    if ctx.reviews:
        parts += ["", "<previous_rounds> (your earlier reviews of this post in this run; the writer was told to apply "
                  "these fixes)"]
        for n, r in enumerate(ctx.reviews[-3:], 1):
            parts.append(f"Round {n}: overall {r['overall']}, scores {json.dumps(r['scores'])}"
                         + (f", red flags {r['red_flags']}" if r["red_flags"] else ""))
            parts += [f"  fix asked: {f}" for f in r["fixes"]]
        parts.append("</previous_rounds>")
    return "\n".join(parts)


def fix_text(f):
    """Fixes are {criterion, fix}; older or scripted ones are plain strings."""
    return f"{f['criterion']}: {f['fix']}" if isinstance(f, dict) else str(f)


def pick_fixes(runs, scores, pl, n=4, target=None):
    """One fix per criterion that keeps the post from passing, lowest score first, each taken from the review
    that scored that criterion lowest; red-flag fixes always come first. Fixes for criteria that already pass are
    dropped, so the writer gets a short list that does not pull in different directions. target: the score a
    criterion must reach to need no fix (default: the passing overall score)."""
    target = target or pl["min_overall"]
    def of(run, crit):
        return [f for f in run.get("fixes", []) if isinstance(f, dict) and f["criterion"] == crit]
    out = [fix_text(f) for r in runs if r.get("red_flags") for f in of(r, "red_flag")][:2]
    failing = sorted(CRITERIA, key=lambda k: scores[k])
    failing = [k for k in failing if scores[k] < pl["min_subscore"]] + \
              [k for k in failing if pl["min_subscore"] <= scores[k] < target]
    for k in failing:
        ranked = sorted(runs, key=lambda r: r["scores"].get(k, 0))
        f = next((f for r in ranked for f in of(r, k)), None)
        if f:
            out.append(fix_text(f))
    out += [fix_text(f) for r in runs for f in r.get("fixes", []) if not isinstance(f, dict)]  # plain-string fixes
    return list(dict.fromkeys(out))[:n]


class EditorAgent(Agent):
    id = "editor"
    title = "Editor Review"
    name = "Quinn"
    role = "Scores accuracy, clarity, hook, value, tone and format; any red flag sends the post back."

    def run(self, ctx, guidance):
        pl = ctx.cfg["pipeline"]
        system = self.prompt(ctx, red_flags=", ".join(RED_FLAGS))
        material = review_material(ctx)
        runs, errors = [], []
        for i in range(pl["review_runs"]):
            try:
                runs.append(self.ask(ctx, system, material, SCHEMA))
            except AgentError as e:
                if e.fatal:
                    raise
                errors.append(str(e))
        if len(runs) < min(2, pl["review_runs"]):
            # fail closed: a post is never accepted without a review
            raise AgentError(f"reviewer produced {len(runs)} result(s): {'; '.join(errors)[:300]}")
        worst = min(runs, key=lambda r: r["overall"])
        scores = {k: min(r["scores"].get(k, 0) for r in runs) for k in CRITERIA}
        flags = sorted({f for r in runs for f in r.get("red_flags", [])})
        passed = worst["overall"] >= pl["min_overall"] and min(scores.values()) >= pl["min_subscore"] and not flags
        fixes = [] if passed else pick_fixes(runs, scores, pl)
        ctx.reviews.append({"overall": worst["overall"], "scores": scores, "red_flags": flags, "fixes": fixes})
        owners = [r["fix_owner"] for r in runs if r["overall"] < pl["min_overall"] or r.get("red_flags")]
        return {"passed": passed, "overall": worst["overall"], "scores": scores, "red_flags": flags,
                "reasons": worst.get("reasons", ""), "fixes": fixes, "runs": len(runs), "errors": errors,
                "fix_owner": max(set(owners), key=owners.count) if owners else worst.get("fix_owner", "writer")}

    def validate(self, ctx, out):
        if out["passed"]:
            return []
        pl = ctx.cfg["pipeline"]
        problems = [f"reviewer overall score {out['overall']} (needs {pl['min_overall']})"]
        problems += [f"red flag: {f}" for f in out["red_flags"]]
        problems += [f"{k} scored {v} (needs {pl['min_subscore']})" for k, v in out["scores"].items()
                     if v < pl["min_subscore"]]
        return problems + out["fixes"]

    def summary(self, out):
        verdict = "passed" if out.get("passed") else f"sent back to {out.get('fix_owner')}"
        return f"score {out.get('overall')} - {verdict}"
