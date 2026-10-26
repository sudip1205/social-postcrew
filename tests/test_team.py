"""Teams: researchers combine verified work, writers compete, the best draft is polished, and members whose
work is consistently bad are replaced by a new hire that learns from their mistakes."""
import json
import unittest
from unittest import mock

from helpers import (GOOD_TEXT, PAGE_URL, QUOTE, TUESDAY, ScriptedLLM, TempWorkspace, fake_fetch, poster_spec,
                     research, review, topic, writer)
from postcrew.agents import credentials as cred_mod
from postcrew.agents import team
from postcrew.crew import run_crew

OTHER_URL = "https://example.org/acme-review"
OTHER_PAGE = ("<html><body><p>Independent testers confirmed that Acme Model 2 handles classification, extraction and "
              "routing well at its launch price, and that it is available to all developers today.</p></body></html>")
OTHER_QUOTE = "it is available to all developers today"
WEAK_TEXT = GOOD_TEXT.replace("Acme Model 2 costs $0.10 per million input tokens.",
                              "Small models are changing how teams automate work.")


def team_ws(ws, research_n=2, writer_n=2, pre_review=True):
    cfg = ws.config()
    cfg["team"].update(research=research_n, writer=writer_n, pre_review=pre_review)
    ws.save_config(cfg)


def base_script(**over):
    s = {"topic": [topic()], "research": [research()], "writer": [writer()], "media": [poster_spec()],
         "editor": [review()], "reviewer": [review(90)],
         "supervisor": [{"action": "retry", "target": "writer", "instructions": ["fix it"], "reason": "test"}]}
    s.update(over)
    return s


def member_ids(ws, role):
    return [m["id"] for m in team.load(ws)["members"] if m["role"] == role]


@mock.patch.object(cred_mod, "check_claude", return_value={"state": "ok", "message": "logged in"})
class TeamTests(unittest.TestCase):
    def test_founding_team_and_personas_reach_the_prompts(self, _):
        with TempWorkspace() as ws:
            team_ws(ws)
            self.assertEqual(member_ids(ws, "research"), ["research-ada", "research-ravi"])
            self.assertEqual(member_ids(ws, "writer"), ["writer-maya", "writer-leo"])
            llm = ScriptedLLM(base_script())
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            writers = [c for c in llm.calls if c["agent"] == "writer"]
            self.assertEqual(sorted(c["member"] for c in writers), ["writer-leo", "writer-maya"])
            self.assertIn("YOUR WORKING STYLE (Maya)", next(c for c in writers if c["member"] == "writer-maya")["system"])
            self.assertEqual(len([c for c in llm.calls if c["agent"] == "reviewer"]), 2)   # one pre-review per draft

    def test_researchers_are_combined_and_bad_quotes_are_left_out(self, _):
        with TempWorkspace() as ws:
            team_ws(ws, writer_n=1, pre_review=False)
            ravi = {"sources": [{"url": OTHER_URL, "title": "Review", "published": "2026-10-12",
                                 "excerpts": [OTHER_QUOTE, "a sentence that is not on the page at all"]}],
                    "facts": [{"claim": "Available to all", "source_url": OTHER_URL, "quote": OTHER_QUOTE},
                              {"claim": "Made up", "source_url": OTHER_URL,
                               "quote": "a sentence that is not on the page at all"}], "notes": ""}
            llm = ScriptedLLM(base_script(**{
                "research@research-ravi": [ravi],
                "research_search@research-ravi": [{"candidates": [{"url": OTHER_URL, "title": "r", "why": "x"}],
                                                   "notes": ""}]}))
            fetch = fake_fetch({PAGE_URL: fake_fetch()(PAGE_URL), OTHER_URL: OTHER_PAGE})
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fetch)
            self.assertTrue(res["ok"], res)
            r = json.loads((ws.runs_dir / res["run_id"] / "research.json").read_text())
            self.assertEqual(sorted(s["url"] for s in r["sources"]), sorted([PAGE_URL, OTHER_URL]))
            self.assertNotIn("Made up", [f["claim"] for f in r["facts"]])
            self.assertIn("Available to all", [f["claim"] for f in r["facts"]])
            stats = {m["id"]: m["recent"][-1]["good"] for m in team.load(ws)["members"] if m["role"] == "research"}
            self.assertEqual(stats, {"research-ada": True, "research-ravi": False})   # Ravi quoted something unreal

    def test_best_draft_is_chosen_by_pre_review(self, _):
        with TempWorkspace() as ws:
            team_ws(ws, research_n=1)
            maya_text = GOOD_TEXT.replace("Start with one boring task", "Begin with one dull task")
            llm = ScriptedLLM(base_script(**{
                "writer@writer-maya": [writer(maya_text)], "writer@writer-leo": [writer(GOOD_TEXT)],
                "reviewer": [review(90)]}))
            # route the pre-review by draft: Maya's draft gets a flag
            orig = llm._call

            def call(agent_id, system, prompt, schema, tools, model, member):
                if agent_id == "reviewer":
                    llm.calls.append({"agent": agent_id, "prompt": prompt, "member": member})
                    from postcrew.llm import LLMResult
                    return LLMResult(data=review(62, flags=["unsupported_claim"]) if "dull task" in prompt
                                     else review(88), cost_usd=0.001, model="fake")
                return orig(agent_id, system, prompt, schema, tools, model, member)
            llm._call = call
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            w = json.loads((ws.runs_dir / res["run_id"] / "writer.json").read_text())
            self.assertEqual((w["author"], w["pre_review"]["overall"]), ("writer-leo", 88))
            self.assertNotIn("dull task", ws.queue()[0]["text"])
            m = {x["id"]: x for x in team.load(ws)["members"]}
            self.assertEqual((m["writer-leo"]["stats"]["chosen"], m["writer-leo"]["stats"]["editor_passed"]), (1, 1))
            self.assertFalse(m["writer-maya"]["recent"][-1]["good"])
            self.assertIn("red flag: unsupported_claim", m["writer-maya"]["recent"][-1]["problems"])

    def test_best_draft_is_polished_before_the_editor_when_it_falls_short(self, _):
        with TempWorkspace() as ws:
            team_ws(ws, research_n=1, writer_n=1)
            llm = ScriptedLLM(base_script(writer=[writer(WEAK_TEXT), writer(GOOD_TEXT)],
                                          reviewer=[review(72, fixes=["Hook with the price"]), review(91)]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            self.assertTrue(ws.queue()[0]["text"].startswith("Acme Model 2 costs $0.10"))
            polish = [c for c in llm.calls if c["agent"] == "writer"][1]
            self.assertIn("Hook with the price", polish["prompt"])
            self.assertIn("<previous_draft>", polish["prompt"])

    def test_consistently_bad_member_is_fired_and_the_new_hire_learns(self, _):
        with TempWorkspace() as ws:
            team_ws(ws)
            cfg = ws.config()
            for i in range(cfg["team"]["fire_window"]):
                team.record(ws, "writer-leo", f"run-{i}", good=False, problems=["the hook is a vague general statement"])
                team.record(ws, "writer-maya", f"run-{i}", good=i % 2 == 0)
            llm = ScriptedLLM({"supervisor": [{"lessons": ["Open with the most concrete sourced fact, never a "
                                                           "general statement."]}]})
            changes = team.review(ws, cfg, llm=llm)
            self.assertEqual([(f["name"], h["name"]) for f, h in changes], [("Leo", "Nora")])
            roster = team.load(ws)
            self.assertEqual([m["name"] for m in roster["members"] if m["role"] == "writer"], ["Maya", "Nora"])
            self.assertEqual(roster["fired"][-1]["name"], "Leo")
            self.assertIn("vague general statement", llm.calls[0]["prompt"])
            nora = next(m for m in roster["members"] if m["name"] == "Nora")
            self.assertIn("Open with the most concrete sourced fact", team.persona_block(ws, nora))
            maya = next(m for m in roster["members"] if m["name"] == "Maya")
            self.assertIn("LESSONS FROM THE TEAM'S PAST MISTAKES", team.persona_block(ws, maya))  # shared lessons
            self.assertIn("replaced by Nora", ws.state("notifications")["items"][-1]["title"])
            self.assertEqual(team.review(ws, cfg, llm=llm), [])                                  # Maya stays

    def test_member_with_too_few_posts_is_not_judged_and_lessons_fall_back_without_a_model(self, _):
        with TempWorkspace() as ws:
            cfg = ws.config()
            for i in range(cfg["team"]["fire_window"] - 1):
                team.record(ws, "research-ada", f"run-{i}", good=False, problems=["quote not on the page"])
            self.assertEqual(team.review(ws, cfg, llm=ScriptedLLM({})), [])
            fired, hired = team.fire(ws, "research-ada", cfg, llm=ScriptedLLM({}), notify_user=False)
            self.assertEqual(hired["role"], "research")
            self.assertEqual(team.lessons(ws, "research"), ["Avoid this past problem: quote not on the page"])

    def test_editor_rejection_counts_against_the_chosen_writer(self, _):
        with TempWorkspace() as ws:
            team_ws(ws, research_n=1, writer_n=1, pre_review=False)
            llm = ScriptedLLM(base_script(editor=[review(60, fixes=["hook"])] * 1 + [review()]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            maya = next(m for m in team.load(ws)["members"] if m["name"] == "Maya")
            self.assertEqual((maya["stats"]["editor_failed"], maya["stats"]["editor_passed"]), (0, 1))
            self.assertTrue(maya["recent"][-1]["good"])        # the revision passed: the last word counts

    def test_stale_story_goes_back_to_the_topic_scout_and_is_not_the_researchers_fault(self, _):
        with TempWorkspace() as ws:
            team_ws(ws, research_n=1, writer_n=1, pre_review=False)
            fresh = research(published="2026-10-11")
            llm = ScriptedLLM(base_script(topic=[topic("Acme Model 1 pricing"), topic()],
                                          research=[research(published="2026-09-01"), fresh],
                                          supervisor=[{"action": "retry", "target": "research",
                                                       "instructions": ["try again"], "reason": "wrong"}]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            evs = [json.loads(l) for l in (ws.runs_dir / res["run_id"] / "events.jsonl").read_text().splitlines()]
            d = next(e for e in evs if e["kind"] == "decision")
            self.assertIn("rewind -> topic", d["message"])
            self.assertIn("2026-09-01", d["data"]["instructions"][0])
            self.assertEqual([c["agent"] for c in llm.calls].count("supervisor"), 0)  # no model needed to decide
            ada = next(m for m in team.load(ws)["members"] if m["name"] == "Ada")
            self.assertTrue(all(r["good"] for r in ada["recent"]))
            topic_prompt = next(c for c in llm.calls if c["agent"] == "topic")["prompt"]
            self.assertIn("published between 2026-10-03 and 2026-10-13", topic_prompt)


class PosterFixTests(unittest.TestCase):
    def test_source_line_is_never_a_cut_off_address(self):
        from postcrew.agents.media import source_footer
        long_url = "https://sierra.ai/blog/introducing-personal-agent-protocol"
        r = {"verified": [{"url": long_url, "verified": True}]}
        self.assertEqual(source_footer(r, long_url), "Source: sierra.ai (link in the first comment)")
        self.assertEqual(source_footer(r, "https://sierra.ai/blog/poppy"), "Source: sierra.ai/blog/poppy")
        self.assertEqual(source_footer({"verified": []}, ""), "")

    def test_poster_numbers_must_be_in_the_post(self):
        from postcrew.checks import poster_number_problems
        self.assertEqual(poster_number_problems("an additional 35 design partners", "35 partners"), [])
        self.assertTrue(poster_number_problems("an additional 35 design partners", "40 partners"))


@mock.patch.object(cred_mod, "check_claude", return_value={"state": "ok", "message": "logged in"})
class EditorRewindTests(unittest.TestCase):
    def test_editor_poster_fixes_reach_the_visual_designer_on_a_rewind(self, _):
        with TempWorkspace() as ws:
            team_ws(ws, research_n=1, writer_n=1, pre_review=False)
            llm = ScriptedLLM(base_script(
                editor=[review(60, flags=["poster_text_mismatch"], fixes=["Writer: tighten the hook",
                                                                          "Media: use the post's wording on the poster"])] * 1
                + [review()],
                supervisor=[{"action": "rewind", "target": "writer", "instructions": ["tighten the hook"],
                             "reason": "text"}]))
            res = run_crew(ws, TUESDAY, llm=llm, fetch=fake_fetch())
            self.assertTrue(res["ok"], res)
            media_prompts = [c["prompt"] for c in llm.calls if c["agent"] == "media"]
            self.assertEqual(len(media_prompts), 2)
            self.assertIn("Media: use the post's wording on the poster", media_prompts[1])
            self.assertNotIn("Writer: tighten the hook", media_prompts[1])
