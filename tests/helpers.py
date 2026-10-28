"""Test doubles: a scripted LLM, a fake web, and a fake LinkedIn. No network, no tokens spent."""
import copy
import shutil
import tempfile
from datetime import date

from postcrew.defaults import YOUTUBE_EXAMPLE_TOPICS
from postcrew.llm import LLMError, LLMResult
from postcrew.workspace import Workspace

PAGE_URL = "https://example.com/news/launch"
PAGE = ("<html><body><h1>Acme Model 2 launch</h1><p>Acme Model 2 is available today for all developers.</p>"
        "<p>Pricing is $0.10 per million input tokens and $0.50 per million output tokens.</p>"
        "<p>Model 2 supports tool use, structured outputs and a long context window, and it is designed for "
        "high-volume work such as classification, extraction and routing.</p></body></html>")
QUOTE = "Pricing is $0.10 per million input tokens and $0.50 per million output tokens."
TUESDAY = date(2026, 10, 13)   # ai-news in the default schedule
SATURDAY = date(2026, 10, 17)  # dev-tip

GOOD_TEXT = ("Acme Model 2 costs $0.10 per million input tokens.\n\n"
             "Acme released Model 2 for all developers this week. Input is $0.10 and output is $0.50 per million "
             "tokens, which makes small, frequent jobs cheap enough to automate without thinking twice.\n\n"
             "What it means in real life:\n"
             "1. Sort support tickets before a person reads them\n"
             "2. Summarize long logs into the three lines that matter\n"
             "3. Tag documents so search finally works\n\n"
             "Start with one boring task and measure it for a week before adding more.\n\n"
             "Which repetitive task would you hand to a cheap model first?\n\n#AI #LLM #Automation")
DEV_TIP = ("Python's default arguments are evaluated once, not on every call.\n\n"
           "That is why a list default keeps growing between calls and surprises people in production code. "
           "The fix is to default to None and create the list inside the function, so each call gets a fresh one. "
           "Linters flag this pattern, but it still slips into code reviews all the time.\n\n"
           "Why it works: None is immutable, so sharing it between calls is harmless.\n\n"
           "Have you been bitten by this one?\n\n#Python #DevTips #SoftwareEngineering")


def topic(t="Acme Model 2 pricing", queries=("acme model 2 pricing",)):
    return {"topic": t, "angle": "what the new price makes worth automating", "why_now": "launched this week",
            "search_queries": list(queries)}


def research(quote=QUOTE, url=PAGE_URL, published="2026-10-11"):
    return {"sources": [{"url": url, "title": "Acme Model 2", "published": published, "excerpts": [quote]}],
            "facts": [{"claim": "Input costs $0.10 per million tokens", "source_url": url, "quote": quote}],
            "notes": ""}


def writer(text=GOOD_TEXT, fc=PAGE_URL):
    return {"text": text, "first_comment": fc}


def poster_spec():
    return {"layout": "points", "title": "Acme Model 2 costs [[$0.10]] per million tokens",
            "items": [{"head": "What launched", "body": "Model 2 for all developers"},
                      {"head": "Price", "body": "$0.10 in, $0.50 out per million tokens"},
                      {"head": "Try it", "body": "Automate one boring task first"}]}


def review(overall=90, flags=(), owner="writer", fixes=()):
    return {"scores": {k: overall for k in ("accuracy", "clarity", "hook", "value", "tone", "format")},
            "overall": overall, "red_flags": list(flags), "reasons": "ok", "fixes": list(fixes), "fix_owner": owner}


class ScriptedLLM:
    """Answers per agent from a queue of responses; a response may be an exception to raise."""

    def __init__(self, script, cost=0.01):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls = []
        self.cost = cost
        self.lock = __import__("threading").Lock()

    def call(self, agent_id, system, prompt, schema, tools=(), cwd=None, model=None, member=None):
        with self.lock:
            return self._call(agent_id, system, prompt, schema, tools, model, member)

    def _call(self, agent_id, system, prompt, schema, tools, model, member):
        self.calls.append({"agent": agent_id, "prompt": prompt, "tools": list(tools), "system": system,
                           "model": model, "member": member})
        key = agent_id
        if member and f"{agent_id}@{member}" in self.script:   # an answer for one team member
            key = f"{agent_id}@{member}"
        if agent_id == "research" and "candidates" in schema.get("properties", {}):
            key = "research_search"  # phase 1 of research: choosing pages
            if member and f"research_search@{member}" in self.script:
                key = f"research_search@{member}"
        q = self.script.get(key) or ([{"candidates": [{"url": PAGE_URL, "title": "Acme", "why": "launch"}],
                                       "notes": ""}] if key == "research_search" else None)
        if not q:
            raise LLMError(f"no scripted answer for {agent_id}", kind="failed")
        item = q.pop(0) if len(q) > 1 else q[0]
        if isinstance(item, Exception):
            raise item
        return LLMResult(data=item, cost_usd=self.cost, model="fake-model", turns=1)

    def agents_called(self):
        return [c["agent"] for c in self.calls]


def fake_fetch(pages=None):
    pages = pages or {PAGE_URL: PAGE}

    def fetch(url, **kw):
        if url not in pages:
            raise OSError("404 not found")
        return pages[url]
    return fetch


class FakeLinkedIn:
    posts = []

    def __init__(self, token, version="202601", fail=None):
        self.token = token
        self.fail = fail

    def userinfo(self):
        from postcrew.linkedin import LinkedInError
        if self.token == "bad":
            raise LinkedInError("HTTP 401", 401)
        return {"sub": "abc123", "name": "Test User"}

    def person_urn(self):
        return "urn:li:person:abc123"

    def upload_image(self, owner, path):
        return "urn:li:image:1"

    def upload_video(self, owner, path, log=print):
        return "urn:li:video:1"

    def create_post(self, owner, text, media_urn=None, title=""):
        FakeLinkedIn.posts.append({"owner": owner, "text": text, "media": media_urn})
        return f"urn:li:share:{len(FakeLinkedIn.posts)}"

    comments = []
    comment_failures = 0  # how many add_comment calls fail before one succeeds

    def add_comment(self, owner, urn, text):
        from postcrew.linkedin import LinkedInError
        if FakeLinkedIn.comment_failures:
            FakeLinkedIn.comment_failures -= 1
            raise LinkedInError("HTTP 404 post not found yet", 404)
        FakeLinkedIn.comments.append({"urn": urn, "text": text})


def claude_ok(cmd, **kw):
    class R:
        stdout = '{"loggedIn": true, "authMethod": "claude.ai"}'
        returncode = 0
    return R()


class TempWorkspace:
    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="postcrew-test-")
        ws = Workspace(self.dir).init()
        cfg = ws.config()
        cfg["notifications"]["desktop"] = False
        cfg["profile"]["handle"] = "example.com/test"
        cfg["team"].update(research=1, writer=1, pre_review=False)  # the crew tests use one of each
        cfg["llm"]["claude_path"] = "/nonexistent/claude"  # a test that forgets to fake the LLM fails, never calls Claude
        yt = cfg["platforms"]["youtube"]   # YouTube starts with no topics; the tests use the four example topics
        yt["categories"] = copy.deepcopy(YOUTUBE_EXAMPLE_TOPICS)
        yt["schedule"]["days"] = {"tue": "explainer", "fri": "short-tip"}
        yt["video"].update(renderer="ffmpeg", pace="normal", target_seconds=45)   # the tests' videos are short and plain
        ws.save_config(cfg)
        self.ws = ws
        return ws

    def __exit__(self, *a):
        shutil.rmtree(self.dir, ignore_errors=True)
