"""The demo provider (`llm.backend: "demo"`): scripted answers, so anyone can watch a full crew run with no AI
account, no API key and no LinkedIn login. Nothing leaves the computer.

Only the answers are scripted. Everything else is the real crew: the Supervisor, every check, the quote
verification (against the one page below, served locally), the poster, the three Editor reads and the
send-back loop. The first Editor round fails on the hook on purpose, so the review loop shows up in Workflow.

The story is made up ("Acme Model 2"). The demo only writes AI news posts.
"""
import re
import time
from datetime import date

from .llm import LLMError, LLMResult

CATEGORY = "ai-news"
URL = "https://demo.postcrew.example/acme-model-2"   # .example never resolves: fetch() below serves it
QUOTE = "Pricing is $0.10 per million input tokens and $0.50 per million output tokens."
PAGE = ("<html><head><title>Acme Model 2 is available today</title></head><body>"
        "<h1>Acme Model 2 is available today</h1><p>Acme Model 2 is available today for all developers.</p>"
        f"<p>{QUOTE}</p>"
        "<p>Model 2 supports tool use, structured outputs and a long context window, and it is designed for "
        "high-volume work such as classification, extraction and routing.</p>"
        "<p>This page is part of the Postcrew demo. Acme and Model 2 are made up.</p></body></html>")

BODY = ("Acme released Model 2 for all developers this week. Input is $0.10 and output is $0.50 per million "
        "tokens, which makes small, frequent jobs cheap enough to automate without thinking twice.\n\n"
        "What it means in real life:\n"
        "1. Sort support tickets before a person reads them\n"
        "2. Summarize long logs into the three lines that matter\n"
        "3. Tag documents so search finally works\n\n"
        "Start with one boring task and measure it for a week before adding more.\n\n"
        "Which repetitive task would you hand to a cheap model first?\n\n#AI #LLM #Automation")
HOOK_1 = "A new model came out this week, and the price is the interesting part."
HOOK_2 = "Acme Model 2 costs $0.10 per million input tokens."
HOOK_FIX = f"Replace the first line with: \"{HOOK_2}\" (lead with the number, not a teaser)"

PLAN_ASPECTS = ["the basics", "the most common mistake", "a worked example", "how to test it", "when not to use it",
                "what to measure", "a cheaper way", "how it fails", "how to explain it to a teammate", "a checklist before you ship"]
PLAN_TOPICS = ["Acme Model 2 pricing", "Structured outputs in practice", "Routing requests to small models",
               "Evaluating a model on your own data", "Caching prompts to cut costs", "Tool use without surprises",
               "What a long context window is good for"]


def fetch(url, **kw):
    """The demo's web: the one page above, and nothing else."""
    if url != URL:
        raise OSError("not available in the demo (only the demo story's page is)")
    return PAGE


def review(overall, hook=None, fixes=()):
    scores = {k: overall for k in ("accuracy", "clarity", "hook", "value", "tone", "format")}
    if hook is not None:
        scores["hook"] = hook
    return {"scores": scores, "overall": overall, "red_flags": [], "reasons": "Demo review.",
            "fixes": list(fixes), "fix_owner": "writer"}


class Demo:
    pause_s = 1.2   # long enough to watch each agent light up in Workflow

    def __init__(self, cfg, secrets=None):
        self.cfg = cfg
        self.editor_calls = 0
        self.sleep = time.sleep

    def available(self):
        return True

    def call(self, agent_id, system, prompt, schema, tools=(), cwd=None, model=None, member=None):
        self.sleep(self.pause_s)
        data = self.answer(agent_id, prompt, schema)
        if data is None:
            raise LLMError(f"the demo has no answer for {agent_id}", kind="failed")
        return LLMResult(data=data, cost_usd=0.0, model="demo", turns=1)

    def answer(self, agent_id, prompt, schema):
        props = schema.get("properties", {})
        if agent_id == "research":
            if "candidates" in props:
                return {"candidates": [{"url": URL, "title": "Acme Model 2 is available today",
                                        "why": "the launch announcement, with prices"}], "notes": ""}
            return {"sources": [{"url": URL, "title": "Acme Model 2 is available today",
                                 "published": date.today().isoformat(), "excerpts": [QUOTE]}],
                    "facts": [{"claim": "Model 2 costs $0.10 per million input tokens and $0.50 per million "
                                        "output tokens", "source_url": URL, "quote": QUOTE}], "notes": ""}
        if agent_id == "topic":
            return {"topic": "Acme Model 2 pricing", "angle": "which everyday jobs the new price makes worth "
                    "automating", "why_now": "it launched this week", "search_queries": ["acme model 2 pricing"]}
        if agent_id == "writer":
            hook = HOOK_2 if self.editor_calls >= 2 else HOOK_1   # the second draft applies the Editor's fix
            return {"text": f"{hook}\n\n{BODY}", "first_comment": f"Source: {URL}"}
        if agent_id == "reviewer":
            return review(89)
        if agent_id == "editor":
            self.editor_calls += 1
            if self.editor_calls <= 2:   # round one: the second read finds the hook weak, so the draft goes back at once
                return review(76, hook=72, fixes=[{"criterion": "hook", "fix": HOOK_FIX}]) \
                    if self.editor_calls == 2 else review(86)
            return review(90)
        if agent_id == "media":
            return {"layout": "points", "kicker": "AI NEWS", "title": "Acme Model 2 costs [[$0.10]] per million tokens",
                    "items": [{"head": "What launched", "body": "Model 2 for all developers"},
                              {"head": "Price", "body": "$0.10 in, $0.50 out per million tokens"},
                              {"head": "Try it", "body": "Automate one boring task first"}]}
        if agent_id == "planner" and "plans" in props:   # the monthly plan: ten different plans for the owner's topic
            topic = (re.search(r"THE OWNER'S TOPIC: (.+)", prompt) or [None, "Your topic"])[1].strip()
            return {"plans": [{"title": f"{topic}: {aspect}"[:90], "angle": f"{aspect} for {topic}",
                               "context": f"Why {aspect} matters for {topic}.", "example": f"A small team meets {aspect} while working on {topic}.",
                               "takeaway": f"Check {aspect} the next time you work on {topic}.", "search_queries": [f"{topic} {aspect}"]}
                              for aspect in PLAN_ASPECTS]}
        if agent_id == "planner":
            days = sorted(set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", prompt)))
            return {"days": [{"date": d, "topic": PLAN_TOPICS[i % len(PLAN_TOPICS)], "angle": "what to try this week",
                              "search_queries": [PLAN_TOPICS[i % len(PLAN_TOPICS)].lower()]}
                             for i, d in enumerate(days)]}
        if agent_id == "supervisor":
            return {"action": "retry", "target": "writer", "instructions": ["fix the problems listed"],
                    "reason": "demo"}
        if "lessons" in props:
            return {"lessons": ["Lead with the most useful number from the source, not a teaser."]}
        return None
