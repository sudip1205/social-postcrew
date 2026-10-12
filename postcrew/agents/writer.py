"""Writer agent: turns the topic and the verified research into the post text."""
import json

from ..checks import link_problems, number_problems, repeat_problem, text_problems
from .base import Agent, guidance_block, recent_block

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


def revision_block(ctx, guidance):
    prev = ctx.previous.get("writer")
    if not (guidance and prev):
        return ""
    return ("\n\nYOUR PREVIOUS DRAFT was sent back. REVISE it: keep what works and change only what the points "
            "below require. Do not add new claims while fixing.\n<previous_draft>\n" + prev["text"] + "\n</previous_draft>")


class WriterAgent(Agent):
    id = "writer"
    title = "Writer"
    role = "Writes the post from verified facts only, in the owner's voice."

    def run(self, ctx, guidance):
        topic = ctx.outputs["topic"]
        system = self.prompt(ctx, min_chars=ctx.cat["min_chars"], max_chars=ctx.cat["max_chars"])
        prompt = (f"Category: {ctx.cat['label']}\nWhat this category needs: {ctx.cat['brief']}\n"
                  f"Length: {ctx.cat['min_chars']}-{ctx.cat['max_chars']} characters.\n"
                  f"Topic: {topic['topic']}\nAngle: {topic['angle']}\n\n"
                  + research_block(ctx.outputs.get("research"))
                  + ("\n\nPOSTS OF THE WEEK (draw the recap only from these):\n" +
                     json.dumps(topic["week_posts"], ensure_ascii=False, indent=1) if topic.get("week_posts") else "")
                  + f"\n\nRecent posts (match the voice, do not repeat structure):\n{recent_block(ctx, 8)}"
                  + revision_block(ctx, guidance)
                  + guidance_block(guidance))
        return self.ask(ctx, system, prompt, SCHEMA)

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
        return f"{len(t)} chars: {t.splitlines()[0][:70] if t else ''}"
