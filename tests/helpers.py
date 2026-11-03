"""Test doubles: a scripted LLM, a fake web, and a fake LinkedIn. No network, no tokens spent."""
import copy
import shutil
import tempfile
from datetime import date

from postcrew.defaults import YOUTUBE_EXAMPLE_TOPICS
from postcrew.llm import LLMError, LLMResult
from postcrew import monthly as _monthly
from postcrew import trends as _trends
from postcrew.workspace import Workspace

_trends.fetch = lambda url, timeout=25: ""   # tests never touch YouTube: niche research then finds nothing and the plans are written without numbers
REAL_PER_TOPIC = _monthly.per_topic
_monthly.per_topic = lambda platform, month, topics: 10   # most tests write ten plans per topic; the counting rules are tested with REAL_PER_TOPIC

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
        # the crew tests run on the weekly schedule the app had before the monthly plan (days are now assigned by hand)
        cfg["schedule"].update(frequency="weekly", days={"mon": "algorithm", "tue": "ai-news", "wed": "build-guide",
                                                         "thu": "tool-spotlight", "fri": "security", "sat": "dev-tip", "sun": "week-recap"})
        cfg["platforms"]["youtube"]["schedule"]["frequency"] = "weekly"
        yt = cfg["platforms"]["youtube"]   # YouTube starts with no topics; the tests use the four example topics
        yt["categories"] = copy.deepcopy(YOUTUBE_EXAMPLE_TOPICS)
        yt["schedule"]["days"] = {"tue": "explainer", "fri": "short-tip"}
        yt["video"].update(renderer="ffmpeg", pace="normal", target_seconds=75, outro="")   # the tests' videos are short and plain
        ws.save_config(cfg)
        self.ws = ws
        return ws

    def __exit__(self, *a):
        shutil.rmtree(self.dir, ignore_errors=True)


def wait_plan_job(get_job, timeout=60):
    """Generate plan runs as a background job: wait for it to end and return it ({"state": "done", "result": {...}} or an error)."""
    import time
    end = time.time() + timeout
    while time.time() < end:
        job = get_job()
        if job.get("state") != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("the plan job did not finish")


# ---------- a quiz Short (postcrew/quiz.py): intro, four A-or-B rounds, the closing card ----------
def _trace(sub, counter, cells, steps):
    return {"kind": "trace", "sub": sub, "counter": counter, "cells": cells, "steps": steps, "src": "", "dst": "", "ms": 0, "fail": False, "fn": "n", "label": "", "bars": []}


def _link(sub, src, dst, ms):
    return {"kind": "link", "sub": sub, "counter": "SERVED", "cells": [], "steps": [], "src": src, "dst": dst, "ms": ms, "fail": False, "fn": "n", "label": "", "bars": []}


def _curve(fn, label):
    return {"kind": "curve", "sub": "work as the list grows", "counter": "STEPS", "cells": [], "steps": [], "src": "", "dst": "", "ms": 0, "fail": False, "fn": fn, "label": label, "bars": []}


def _step(active, note, found=(), out=()):
    return {"active": list(active), "found": list(found), "out": list(out), "note": note}


QUIZ_ROUNDS = [
    {"part": "idea", "on_screen": "Two Sum. *Which is faster?*", "winner": "B", "name": "Two Sum", "answer": "B: hash map, one pass",
     "badge": "ONE PASS, NO NESTED LOOP", "caption": "One pass beats checking every pair: four steps, not ten.",
     "pick": "Let's find two numbers that add up to nine. Does the nested loop win, or the hash map? Pick A or B.",
     "reveal": "It is the hash map. For each number we ask the map if the partner we need is already there, so we look at the list only once.",
     "a": _trace("nested loops, every pair", "CHECKS", ["3", "8", "2", "7", "11", "1"],
                 [_step([0, 1], "3 + 8 = 11, no"), _step([0, 2], "3 + 2 = 5, no"), _step([1, 2], "8 + 2 = 10, no"), _step([2, 3], "2 + 7 = 9, yes", found=[2, 3])]),
     "b": _trace("hash map, one pass", "STEPS", ["3", "8", "2", "7", "11", "1"],
                 [_step([0], "need 6, not seen"), _step([1], "need 1, not seen"), _step([2], "need 7, not seen"), _step([3], "need 2, in the map", found=[2, 3])])},
    {"part": "idea", "on_screen": "Reading data. *Which is faster?*", "winner": "A", "name": "Reading data", "answer": "A: a cache in front",
     "badge": "CACHE HIT, NO DATABASE TRIP", "caption": "Memory answers in two milliseconds. The database needs one hundred and twenty.",
     "pick": "Your app reads the same profile again and again. Which way answers faster? Pick A or B.",
     "reveal": "It is the cache. Memory answers in about two milliseconds, while a trip to the database takes much longer, so the cache serves many more readers.",
     "a": _link("app to cache", "App", "Cache", 2), "b": _link("app to database", "App", "Database", 120)},
    {"part": "example", "on_screen": "Find twenty eight. *Which looks less?*", "winner": "B", "name": "Sorted search", "answer": "B: binary search",
     "badge": "HALVE THE LIST EACH LOOK", "caption": "Binary search halves the list each look: five looks, not fourteen.",
     "pick": "A sorted list holds the even numbers up to forty. Which way finds twenty eight with fewer looks? Pick A or B.",
     "reveal": "It is binary search. Each look throws away half of what is left, so five looks are enough where a plain scan needs fourteen.",
     "a": _trace("linear scan, find 28", "LOOKS", ["2", "4", "6", "8", "10", "12", "14", "16", "18", "20"],
                 [_step([0], "2, no"), _step([1], "4, no", out=[0]), _step([2], "6, no", out=[0, 1]), _step([3], "8, keep going", out=[0, 1, 2])]),
     "b": _trace("binary search, find 28", "LOOKS", ["2", "4", "6", "8", "10", "12", "14", "16", "18", "20"],
                 [_step([4], "10, go right"), _step([7], "16, go right", out=[0, 1, 2, 3, 4]), _step([8], "18, found", found=[8], out=[0, 1, 2, 3, 4, 5, 6, 7])])},
    {"part": "mistake", "on_screen": "The common mistake. *Which scales better?*", "winner": "B", "name": "Scaling", "answer": "B: linear beats quadratic",
     "badge": "LINEAR STAYS LOW", "caption": "At ten items it is one hundred steps against ten. The gap only grows.",
     "pick": "A common mistake is to nest a loop inside a loop without thinking about the size. Which one scales better? Pick A or B.",
     "reveal": "It is the single pass. The nested loop does ten times ten steps at ten items, and the gap widens with every item you add.",
     "a": _curve("n^2", "O(n²)"), "b": _curve("n", "O(n)")},
]


def quiz_script(rounds=None, closing=None):
    """A complete quiz Short script as the Script Writer returns it (finish() has composed the narration of each round)."""
    from postcrew.agents.script import finish
    blank = {"items": [], "code": "", "language": "", "nodes": [], "edges": [], "cells": [], "steps": [], "seconds": 0}
    scenes = [dict(blank, layout="statement", part="intro", on_screen="One is faster. *Can you tell?*",
                   narration="Two ways of solving the same problem can look equally good, until you watch them run side by side. Can you tell which one is faster? There are four rounds, so keep score.")]
    for r in rounds or QUIZ_ROUNDS:
        v = copy.deepcopy({k: r[k] for k in ("pick", "reveal", "a", "b", "winner", "badge", "caption", "name", "answer")})
        scenes.append(dict(blank, layout="versus", part=r["part"], on_screen=r["on_screen"], narration="", versus=v))
    scenes.append(dict(blank, layout="statement", part="closing", on_screen="Like · Comment · Subscribe",
                       narration=closing or "How many did you get? Comment your score. And if this was useful, please like, subscribe, and share it with someone who is learning."))
    return finish({"title": "Two Sum, caches and search: can you pick the faster one?", "tags": ["algorithms", "two sum", "hash map", "cache", "binary search"],
                   "description": "Four quick rounds, A or B: which way is faster? Two Sum, a cache, binary search and how work grows. Comment your score.",
                   "thumbnail_text": "Pick the faster", "scenes": scenes})
