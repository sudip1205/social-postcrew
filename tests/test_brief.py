import json
import re
import shutil
import unittest
from pathlib import Path
from unittest import mock

from helpers import SATURDAY, ScriptedLLM, TempWorkspace, fake_fetch, research, review, writer
from postcrew import brief
from postcrew.agents import credentials as cred_mod
from postcrew.agents.planner import load_plan, set_entry
from postcrew.crew import run_crew
from postcrew.render import sysflow

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = json.loads((ROOT / "workspace" / "briefs" / "sample_agent_spec.json").read_text()) \
    if (ROOT / "workspace" / "briefs" / "sample_agent_spec.json").exists() else None

TEXT = """Context: why this matters.
Example: a refund agent with one admin token.
Example type: scenario
Takeaway: use token exchange
Pattern: before after
Must include:
- token exchange
Avoid:
- vendor names
Question: How do you issue agent credentials?
Visual: system-flow
Systems:
- cust | Customer | user | asks
- agent | Support agent | agent | acts
- api | API Gateway | api-gateway | checks
Flow:
Scene: Before
cust > agent | Refund 1042 | request | "please refund" | The customer asks
agent > api | POST refund | request | Bearer admin 24h | The agent calls the API
api > agent | Done | response | 200 OK | Everything is refunded
"""


class BriefParsing(unittest.TestCase):
    def test_text_round_trips(self):
        b = brief.normalize(TEXT)
        self.assertEqual(b["pattern"], "before-after")
        self.assertEqual(b["example_kind"], "scenario")
        self.assertEqual([s["id"] for s in b["visual"]["systems"]], ["cust", "agent", "api"])
        self.assertEqual(len(b["visual"]["flow"]), 3)
        self.assertEqual(brief.normalize(brief.to_text(b)), b)

    def test_bad_flow_line_names_the_problem(self):
        with self.assertRaises(brief.BriefError):
            brief.normalize("Visual: system-flow\nFlow:\nnot a flow line")

    def test_only_gaps_are_filled_and_marked_generated(self):
        b = brief.normalize("Context: mine\nExample: mine too")
        got = {"context": "AI", "example": "AI", "takeaway": "AI takeaway", "pattern": "checklist", "question": "Q?"}
        out = brief.merge_generated(b, got, ["context", "takeaway", "pattern", "question"])
        self.assertEqual(out["context"], "AI")  # only listed gaps are used by the caller
        gaps = brief.missing(b, {"media": "poster"})
        self.assertNotIn("context", gaps)
        self.assertIn("takeaway", gaps)

    def test_numbers_the_owner_wrote_are_supplied(self):
        b = brief.normalize("Context: tokens live 24 hours and 5 minutes, refund $1,200")
        self.assertIn("$1,200", brief.numbers_in(b))

    def test_week_file_parses(self):
        f = ROOT / "workspace" / "briefs" / "identity-ai-week.md"
        if not f.exists():
            self.skipTest("no week file")
        parts = re.split(r"(?m)^##\s+(\d{4}-\d{2}-\d{2})\s*$", f.read_text())
        self.assertGreaterEqual(len(parts), 13)
        for body in parts[2::2]:
            b = brief.normalize(brief.parse_text(body))
            self.assertTrue(b.get("example"))


class SysflowSpec(unittest.TestCase):
    @unittest.skipUnless(SAMPLE, "no sample spec")
    def test_sample_is_valid_and_draws_every_phase(self):
        self.assertEqual(sysflow.validate_spec(SAMPLE), [])
        r = sysflow.Renderer(SAMPLE, "example.com")
        self.assertTrue(sysflow.MIN_SECONDS <= r.total <= sysflow.MAX_SECONDS)
        for t in (0.5, r.total / 2, r.total - 0.1):
            img = r.frame(t)
            self.assertEqual(img.size, (1080, 1350))

    @unittest.skipUnless(SAMPLE, "no sample spec")
    def test_unknown_component_and_long_label_are_reported(self):
        bad = json.loads(json.dumps(SAMPLE))
        bad["scenes"][0]["steps"][0]["to"] = "nowhere"
        bad["scenes"][0]["steps"][1]["label"] = "x" * 40
        problems = sysflow.validate_spec(bad)
        self.assertTrue(any("nowhere" in p for p in problems), problems)
        self.assertTrue(any("label" in p for p in problems), problems)


@mock.patch.object(cred_mod, "check_claude", return_value={"state": "ok", "message": "logged in"})
class BriefedRun(unittest.TestCase):
    @unittest.skipUnless(SAMPLE and shutil.which("ffmpeg"), "needs ffmpeg and the sample spec")
    def test_planned_brief_reaches_writer_and_editor_and_builds_the_animation(self, _):
        post_text = ("Why an AI agent needs its own token\n\n" + (
            "Picture a refund agent. A Customer asks for a refund, the Support agent calls the API Gateway with one "
            "broad admin token, and the Orders DB trusts it. An Attacker who plants a prompt gets every order refunded. "
            "With token exchange the Support agent asks the Auth server for a narrow token that covers one refund and expires in 300 seconds, "
            "and the API Gateway checks that scope on every call. ") * 2 +
            "\n\nHow are you issuing credentials to your agents today?\n\n#AI #Security #Identity")
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["categories"]["briefed"].update(briefing="owner", context="CTX-ABOUT-TYPE", plan_context="CTX-HOW-TO-PLAN")
            ws.save_config(cfg)
            b = brief.normalize(TEXT)
            set_entry(ws, SATURDAY.isoformat(), {"category": "briefed", "topic": "Why an AI agent needs its own token",
                                                 "angle": "token exchange", "search_queries": [], "source": "manual",
                                                 "rejected": [], "brief": b})
            self.assertTrue(load_plan(ws)[SATURDAY.isoformat()]["brief"])
            llm = ScriptedLLM({"topic": [{"topic": "x" * 6, "angle": "a", "why_now": "w", "search_queries": []}],
                               "research": [research()], "writer": [writer(post_text, "")], "media": [SAMPLE],
                               "editor": [review()]})
            res = run_crew(ws, SATURDAY, "briefed", llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            wprompt = next(c["prompt"] for c in llm.calls if c["agent"] == "writer")
            self.assertIn("OWNER'S BRIEF", wprompt)
            self.assertIn("CTX-ABOUT-TYPE", wprompt)
            self.assertNotIn("characters.\n", wprompt.split("Length:")[1].split("\n")[0].replace("3000 characters at most).", ""))
            self.assertEqual(ws.queue()[0]["media_kind"], "video")
            self.assertIn("Picture", wprompt)
            self.assertIn("before-after".replace("-", " ").title().split()[0], wprompt.title())
            eprompt = next(c for c in llm.calls if c["agent"] == "editor")
            self.assertIn("<owner_brief>", eprompt["prompt"])
            self.assertIn("THE OWNER WROTE A BRIEF", eprompt["system"])
            post = ws.queue()[0]
            self.assertEqual(post["media_kind"], "video")
            self.assertTrue(post["media"].endswith(".mp4"))

    def test_brief_is_ignored_when_the_category_says_off(self, _):
        with TempWorkspace() as ws:
            c = ws.config()["categories"]["briefed"]
            c["briefing"] = "off"
            self.assertEqual(brief.briefing_mode(c), "off")


if __name__ == "__main__":
    unittest.main()


class SysflowTextForEditor(unittest.TestCase):
    @unittest.skipUnless(SAMPLE, "no sample spec")
    def test_labels_are_not_double_numbered_and_layout_never_rejects(self):
        spec = json.loads(json.dumps(SAMPLE))
        spec["scenes"][0]["steps"][0]["label"] = "1. Refund 1042"
        self.assertEqual(sysflow.validate_spec(spec), [])
        text = sysflow.shown_text(spec)
        self.assertIn("Step 1: Customer to Support agent: Refund 1042", text)
        self.assertNotIn("(attacker)", text)   # component kinds are not on screen


class SysflowNumbers(unittest.TestCase):
    @unittest.skipUnless(SAMPLE, "no sample spec")
    def test_payload_numbers_are_not_claims(self):
        spec = json.loads(json.dumps(SAMPLE))
        spec["scenes"][0]["steps"][0]["payload"] = "retry 10 times, port 8443"
        self.assertNotIn("8443", sysflow.claim_text(spec))
        spec["scenes"][0]["steps"][0]["caption"] = "It retries 10 times."
        self.assertIn("10 times", sysflow.claim_text(spec))
