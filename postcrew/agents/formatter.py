"""Formatter agent: turns the approved draft into the exact LinkedIn post. Deterministic, no LLM.

- normalizes line endings, trailing spaces and blank lines; removes zero-width characters
- moves any link out of the body into the first comment (links in the body reduce reach)
- puts hashtags on one final line, de-duplicated, at most 5
- checks the hook fits above LinkedIn's "...see more" fold and the 3,000 character limit
"""
import re

from ..checks import LINKEDIN_LIMIT, URL
from .base import Agent

FOLD = 210
TAG = re.compile(r"(?<!\w)#[A-Za-z][\w]*")


def format_post(text, first_comment=""):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[​‌‍﻿]", "", text)
    text = "\n".join(ln.rstrip() for ln in text.split("\n"))
    links = URL.findall(text)
    for u in links:
        text = text.replace(u, "").replace("()", "")
    lines = text.strip().split("\n")
    tags = []
    while lines and (not lines[-1].strip() or all(TAG.fullmatch(w) for w in lines[-1].split())):
        tags = lines.pop().split() + tags
    body = "\n".join(lines)
    seen, final_tags = set(), []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            final_tags.append(t)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    out = body + ("\n\n" + " ".join(final_tags[:5]) if final_tags else "")
    fc = first_comment.strip() or (links[0] if links else "")
    return out, fc, links


class FormatterAgent(Agent):
    id = "formatter"
    title = "Formatter"
    name = "Kai"
    role = "Applies LinkedIn formatting: hook above the fold, links to the first comment, hashtags last."
    uses_llm = False

    def run(self, ctx, guidance):
        w, m = ctx.outputs["writer"], ctx.outputs.get("media") or {}
        text, fc, moved = format_post(w["text"], w.get("first_comment", ""))
        return {"text": text, "first_comment": fc, "moved_links": moved, "media_path": m.get("path"),
                "media_kind": m.get("kind"), "title": ctx.outputs["topic"]["topic"], "chars": len(text)}

    def validate(self, ctx, out):
        problems = []
        if out["chars"] > LINKEDIN_LIMIT:
            problems.append(f"post is {out['chars']} characters; LinkedIn allows {LINKEDIN_LIMIT}")
        hook = out["text"].split("\n", 1)[0]
        if len(hook) > FOLD:
            problems.append(f"the first line is {len(hook)} chars and will be cut by '...see more' ({FOLD}); "
                            f"shorten the hook")
        if ctx.cat["media"] != "none" and not out.get("media_path"):
            problems.append("media is missing")
        return problems

    def summary(self, out):
        return f"{out['chars']} chars" + (f", moved {len(out['moved_links'])} link(s)" if out["moved_links"] else "")
