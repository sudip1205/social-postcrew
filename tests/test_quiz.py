"""The quiz Short: the round's checks, the narration it is spoken as, the props it is drawn from, and where it applies."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import helpers  # noqa: E402
from helpers import QUIZ_ROUNDS, quiz_script  # noqa: E402
from postcrew import checks, platforms, quiz  # noqa: E402
from postcrew.agents.graphics import GraphicsAgent  # noqa: E402
from postcrew.agents.script import SCHEMA, finish  # noqa: E402
from postcrew.render import hyperframes as hf, looks, remotion as rm  # noqa: E402

OUTRO = "If this was useful, please like, comment and subscribe. And if you liked it, share it with someone who would find it helpful."
CAT = {"id": "short", "label": "Short video", "kicker": "SHORT"}


def cfg(**video):
    return {"video": dict({"format": "short", "target_seconds": 90, "renderer": "remotion", "outro": OUTRO, "pace": "slow"}, **video)}


def spec(**video):
    return platforms.video_spec(cfg(**video))


def problems(script, **video):
    return checks.script_problems(script, spec(**video), CAT, {})


def with_round(i, **over):
    rounds = copy.deepcopy(QUIZ_ROUNDS)
    rounds[i].update(over)
    return quiz_script(rounds)


class WhereItApplies(unittest.TestCase):
    def test_a_short_drawn_by_remotion_is_a_quiz_with_the_dark_look(self):
        s = spec()
        self.assertTrue(s["quiz"])
        self.assertEqual(s["look"], "neon")

    def test_it_can_be_turned_off_and_a_long_video_is_never_a_quiz(self):
        self.assertFalse(spec(short_style="classic")["quiz"])
        self.assertFalse(spec(format="long", target_seconds=600)["quiz"])
        self.assertFalse(spec(renderer="ffmpeg")["quiz"])
        self.assertEqual(spec(look="ink")["look"], "ink")   # a look chosen in Settings stays

    def test_the_dark_look_is_a_look(self):
        self.assertIn("neon", looks.CHOICES)
        self.assertEqual(looks.theme("neon")["bg"], "#050B16")

    def test_the_storyboard_artist_leaves_a_quiz_alone(self):
        class Ctx:
            video = spec()
            cfg = cfg()
        self.assertFalse(GraphicsAgent().applies(Ctx))

    def test_the_writer_may_answer_with_a_round(self):
        scene = SCHEMA["properties"]["scenes"]["items"]
        self.assertIn("versus", scene["properties"]["layout"]["enum"])
        self.assertEqual(scene["properties"]["versus"], quiz.VERSUS)
        self.assertNotIn("versus", scene["required"])   # only a round has one


class SpokenAsOneScene(unittest.TestCase):
    def test_a_round_is_the_question_the_countdown_and_the_explanation(self):
        sc = quiz_script()["scenes"][1]
        self.assertIn(" Pick A or B. Three, two, one. It is the hash map.", sc["narration"])
        self.assertGreater(sc["seconds"], 8)

    def test_a_countdown_the_writer_wrote_is_not_said_twice(self):
        sc = {"layout": "versus", "versus": {"pick": "Which is faster? Pick A or B. Three, two, one.", "reveal": "It is B."}}
        self.assertEqual(quiz.compose(sc), "Which is faster? Pick A or B. Three, two, one. It is B.")

    def test_the_text_is_the_scenes_in_order(self):
        script = quiz_script()
        self.assertEqual(" ".join(script["text"].split()), " ".join(" ".join(sc["narration"] for sc in script["scenes"]).split()))


class TheChecks(unittest.TestCase):
    def test_a_good_quiz_passes(self):
        self.assertEqual(problems(quiz_script()), [])

    def test_too_few_rounds(self):
        script = quiz_script(QUIZ_ROUNDS[:2])
        self.assertTrue(any("quiz of 3 to 5 rounds" in p for p in problems(script)))

    def test_every_round_won_by_the_same_letter(self):
        rounds = copy.deepcopy(QUIZ_ROUNDS)
        for r in rounds:
            r["winner"] = "B"
        self.assertTrue(any("same winner" in p for p in problems(quiz_script(rounds))))

    def test_the_two_tiles_must_be_the_same_kind(self):
        script = quiz_script()
        script["scenes"][1]["versus"]["a"] = dict(script["scenes"][2]["versus"]["a"])
        self.assertTrue(any("same kind" in p for p in problems(script)))

    def test_a_trace_step_must_name_real_cells(self):
        script = quiz_script()
        script["scenes"][1]["versus"]["a"]["steps"][0]["active"] = [0, 9]
        self.assertTrue(any("step 1 must name the cells" in p for p in problems(script)))

    def test_two_curves_that_grow_the_same_are_no_comparison(self):
        script = quiz_script()
        script["scenes"][4]["versus"]["b"]["fn"] = "n^2"
        self.assertTrue(any("grow the same way" in p for p in problems(script)))

    def test_a_scene_between_the_intro_and_the_closing_is_a_round(self):
        script = quiz_script()
        script["scenes"][2] = dict(script["scenes"][2], layout="statement", versus=None)
        got = problems(script)
        self.assertTrue(any("only 'versus' rounds" in p for p in got))

    def test_the_arc_still_ends_on_the_mistake_before_the_closing(self):
        script = quiz_script()
        script["scenes"][4]["part"] = "idea"
        self.assertTrue(any("mistake" in p for p in problems(script)))

    def test_a_round_needs_its_fields(self):
        script = quiz_script()
        script["scenes"][3]["versus"]["badge"] = ""
        self.assertTrue(any("'badge'" in p for p in problems(script)))

    def test_an_owners_own_script_is_not_forced_into_rounds(self):
        classic = helpers.quiz_script()
        classic["source"] = "own"
        classic["scenes"] = [s for s in classic["scenes"] if s["layout"] != "versus"] or classic["scenes"]
        self.assertFalse(any("quiz of" in p for p in problems(classic)))

    def test_bars_and_links_are_checked_too(self):
        bars = {"kind": "bars", "sub": "cost of each way", "counter": "", "cells": [], "steps": [], "src": "", "dst": "", "ms": 0, "fail": False, "fn": "n",
                "label": "ms", "bars": ["Database|120", "Cache|2"]}
        self.assertEqual(quiz.tile_problems(bars, "A"), [])
        self.assertTrue(quiz.tile_problems(dict(bars, bars=["Database|many", "Cache|2"]), "A"))
        link = dict(bars, kind="link", src="App", dst="Cache", ms=2)
        self.assertEqual(quiz.tile_problems(link, "B"), [])
        self.assertTrue(quiz.tile_problems(dict(link, ms=0), "B"))


class ThePropsItIsDrawnFrom(unittest.TestCase):
    def setUp(self):
        self.script = quiz_script()
        scenes = rm.mark_closing([dict(s) for s in self.script["scenes"]], spec())
        self.props, self.lengths = rm.build_props(scenes, "short", None, look=spec()["look"])

    def test_a_round_knows_when_the_answer_comes_and_when_to_count(self):
        sc = self.props["scenes"][1]
        v = sc["versus"]
        self.assertEqual((v["round"], v["rounds"]), (1, 4))
        self.assertEqual(len(v["count_at"]), 3)
        self.assertEqual(v["count_at"], sorted(v["count_at"]))
        self.assertLess(v["count_at"][-1], v["reveal_at"])
        self.assertLess(v["reveal_at"], sc["seconds"])
        self.assertEqual(sc["captions"], [])
        json.dumps(self.props)

    def test_both_curves_share_one_scale(self):
        v = self.props["scenes"][4]["versus"]
        self.assertEqual(v["a"]["ymax"], v["b"]["ymax"])
        self.assertEqual(v["a"]["points"][-1][1], 1.0)
        self.assertLess(v["b"]["points"][-1][1], 0.2)
        self.assertEqual((v["a"]["tone"], v["b"]["tone"]), ("bad", "good"))

    def test_a_faster_link_runs_faster_and_is_the_good_one(self):
        v = self.props["scenes"][2]["versus"]
        self.assertLess(v["a"]["period"], v["b"]["period"])
        self.assertEqual((v["a"]["tone"], v["b"]["tone"]), ("good", "bad"))

    def test_the_closing_card_carries_the_answer_key(self):
        last = self.props["scenes"][-1]
        self.assertEqual([r["name"] for r in last["answers"]], ["Two Sum", "Reading data", "Sorted search", "Scaling"])
        self.assertTrue(last["closing"])

    def test_the_whole_quiz_is_drawn_by_remotion_in_one_style(self):
        for sc in self.props["scenes"]:
            self.assertEqual(hf.engine_for(sc), "remotion", sc["layout"])

    def test_it_is_a_dark_page(self):
        self.assertEqual(self.props["theme"]["name"], "neon")

    def test_a_video_that_is_not_a_quiz_is_unchanged(self):
        props, _ = rm.build_props([{"layout": "statement", "on_screen": "Hello", "narration": "Hello there.", "items": []}], "short", None)
        self.assertNotIn("engine", props["scenes"][0])
        self.assertNotIn("answers", props["scenes"][0])


class ThePrompt(unittest.TestCase):
    def test_the_quiz_prompt_only_uses_values_the_writer_fills_in(self):
        import re
        text = (Path(__file__).resolve().parent.parent / "postcrew" / "prompts" / "youtube" / "writer_quiz.md").read_text()
        self.assertEqual(set(re.findall(r"\{\{(\w+)\}\}", text)) - {"name", "voice", "outro", "short_max_words"}, set())

    def test_the_prompt_teaches_every_kind_of_tile_the_screen_can_draw(self):
        text = (Path(__file__).resolve().parent.parent / "postcrew" / "prompts" / "youtube" / "writer_quiz.md").read_text()
        for kind in quiz.KINDS:
            self.assertIn(f"* {kind}:", text)


if __name__ == "__main__":
    unittest.main()
