"""Code plus a picture of it running: the recursion the writer describes is run by the app, so what the screen shows is exactly right."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from postcrew import checks, codeviz, platforms  # noqa: E402
from postcrew.agents.graphics import GraphicsAgent  # noqa: E402
from postcrew.agents.script import SCHEMA, finish  # noqa: E402
from postcrew.render import hyperframes as hf, looks, remotion as rm  # noqa: E402

REC = "def climb(n):\n    if n <= 1:\n        return 1\n    return climb(n - 1) + climb(n - 2)"
MEMO = "memo = {}\ndef climb(n):\n    if n <= 1:\n        return 1\n    if n in memo:\n        return memo[n]\n    memo[n] = climb(n - 1) + climb(n - 2)\n    return memo[n]"
TABLE = "def climb(n):\n    dp = [1, 1]\n    for i in range(2, n + 1):\n        dp.append(dp[i - 1] + dp[i - 2])\n    return dp[n]"
BASE = {"fn": "f", "n": 5, "steps": [1, 2], "base": ["0:1", "1:1"], "combine": "sum", "plus": 0, "title": "calls for climb(5)"}
PLAIN = dict(BASE, kind="calls", memo=False, line_call=4, line_base=3, line_hit=0, line_return=4, line_fill=0)
MEMOIZED = dict(BASE, kind="calls", memo=True, line_call=7, line_base=4, line_hit=6, line_return=8, line_fill=0)
TABLED = dict(BASE, kind="table", memo=False, line_call=0, line_base=2, line_hit=0, line_return=0, line_fill=4)
OUTRO = "If this was useful, please like, comment and subscribe. And if you liked it, share it with someone who would find it helpful."


class RunTheRecursion(unittest.TestCase):
    def test_the_plain_tree_has_the_calls_the_code_makes(self):
        sim, why = codeviz.simulate_calls(PLAIN)
        self.assertIsNone(why)
        self.assertEqual(sum(1 for e in sim["events"] if e["kind"] == "call"), 15)
        self.assertEqual(sim["nodes"][0]["value"], 8)
        self.assertEqual(sum(1 for n in sim["nodes"] if n["dup"]), 9)   # the repeated work

    def test_a_memo_answers_repeated_calls_at_once(self):
        sim, _ = codeviz.simulate_calls(MEMOIZED)
        self.assertEqual(sum(1 for e in sim["events"] if e["kind"] == "call"), 9)
        self.assertEqual(sum(1 for e in sim["events"] if e["kind"] == "hit"), 2)
        self.assertEqual(sim["nodes"][0]["value"], 8)

    def test_the_table_fills_from_the_bottom(self):
        sim, _ = codeviz.simulate_table(TABLED)
        self.assertEqual([c["value"] for c in sim["cells"]], [1, 1, 2, 3, 5, 8])
        self.assertEqual(sim["cells"][5]["from"], [4, 3])

    def test_min_and_plus_make_a_coin_change_style_recurrence(self):
        v = dict(PLAIN, n=4, steps=[1, 3], base=["0:0"], combine="min", plus=1)
        sim, _ = codeviz.simulate_calls(v)
        self.assertEqual(sim["nodes"][0]["value"], 2)   # 4 = 3 + 1

    def test_a_tree_too_big_to_read_is_refused(self):
        sim, why = codeviz.simulate_calls(dict(PLAIN, n=8, steps=[1, 2, 3]))
        self.assertIsNone(sim)
        self.assertIn("more than 40 calls", why)
        self.assertTrue(any("more than 40 calls" in p for p in codeviz.problems(dict(PLAIN, n=6, steps=[1, 1, 2]), REC, 2)))


class TheChecks(unittest.TestCase):
    def test_a_good_description_passes(self):
        for v, code in ((PLAIN, REC), (MEMOIZED, MEMO), (TABLED, TABLE)):
            self.assertEqual(codeviz.problems(v, code, 2), [], v["kind"])

    def test_a_line_that_is_not_in_the_code_is_refused(self):
        self.assertTrue(any("line_call" in p for p in codeviz.problems(dict(PLAIN, line_call=9), REC, 2)))

    def test_the_steps_the_picture_needs_must_point_at_lines(self):
        self.assertTrue(any("line_base" in p for p in codeviz.problems(dict(MEMOIZED, line_base=0), MEMO, 2)))
        self.assertTrue(any("line_hit" in p for p in codeviz.problems(dict(MEMOIZED, line_hit=0), MEMO, 2)))
        self.assertTrue(any("line_fill" in p for p in codeviz.problems(dict(TABLED, line_fill=0), TABLE, 2)))

    def test_base_cases_and_size(self):
        self.assertTrue(codeviz.problems(dict(PLAIN, base=[]), REC, 2))
        self.assertTrue(codeviz.problems(dict(PLAIN, base=["zero:1"]), REC, 2))
        self.assertTrue(any("viz.n" in p for p in codeviz.problems(dict(PLAIN, n=9), REC, 2)))
        self.assertEqual(codeviz.problems(dict(MEMOIZED, n=9), MEMO, 2), [])   # a memo stays small at 9

    def test_a_codeviz_scene_in_a_script(self):
        scene = {"layout": "codeviz", "part": "idea", "narration": "Let us write the plain version and watch the tree of calls grow. See the glowing calls? The same stair is solved again and again, and that repeated work is the problem we will fix next.", "on_screen": "Plain recursion", "items": [], "code": REC, "language": "python",
                 "nodes": [], "edges": [], "cells": [], "steps": [], "seconds": 0, "viz": PLAIN}
        spec = platforms.video_spec({"video": {"format": "short", "target_seconds": 90, "renderer": "remotion", "outro": OUTRO}})
        problems = checks.script_problems(finish({"title": "Climbing stairs, step by step", "description": "x" * 60, "tags": ["a", "b", "c"], "thumbnail_text": "Stairs", "scenes": [scene]}),
                                          spec, {"id": "s", "label": "Short", "kicker": "S"}, {})
        self.assertFalse([p for p in problems if "scene 1:" in p and ("viz" in p or "codeviz" in p or "layout" in p)], problems)
        bad = dict(scene, viz=dict(PLAIN, line_call=99))
        problems = checks.script_problems(finish({"title": "Climbing stairs, step by step", "description": "x" * 60, "tags": ["a", "b", "c"], "thumbnail_text": "Stairs", "scenes": [bad]}),
                                          spec, {"id": "s", "label": "Short", "kicker": "S"}, {})
        self.assertTrue(any("viz.line_call" in p for p in problems))

    def test_the_writer_may_answer_with_one(self):
        scene = SCHEMA["properties"]["scenes"]["items"]
        self.assertIn("codeviz", scene["properties"]["layout"]["enum"])
        self.assertEqual(scene["properties"]["viz"], codeviz.VIZ)
        self.assertNotIn("viz", scene["required"])

    def test_it_counts_as_the_hands_on_part_of_a_short(self):
        scenes = [{"layout": "statement", "part": "intro", "narration": "Imagine stairs."}] + \
                 [{"layout": "codeviz", "part": "idea", "narration": "word " * 40, "viz": PLAIN, "code": REC}] + \
                 [{"layout": "statement", "part": "closing", "narration": "Bye."}] * 4
        self.assertFalse([p for p in checks.storyboard_problems(scenes, {"format": "short", "artist": True, "wps": 2.5}) if "builds or solves nothing" in p])

    def test_a_long_code_walk_through_is_not_split_or_redrawn(self):
        long = {"layout": "codeviz", "part": "idea", "narration": ("Watch the tree grow now. " * 14).strip(), "viz": PLAIN, "code": REC}
        self.assertEqual(len(checks.split_long_scenes([long], {"format": "short", "wps": 2.5})), 1)


class TheProps(unittest.TestCase):
    def props(self, viz, code, seconds=22):
        scene = {"layout": "codeviz", "on_screen": "Plain recursion", "narration": "Watch the tree grow. " * 5, "code": code, "language": "python", "items": [], "viz": viz, "seconds": seconds}
        out, _ = rm.build_props([scene], "short", None, look="neon")
        return out["scenes"][0]

    def test_every_step_lights_a_line_and_the_steps_are_in_time_order(self):
        v = self.props(PLAIN, REC)["viz"]
        times = [e["t"] for e in v["events"]]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(v["events"]), 30)
        self.assertLess(times[-1], 22)
        self.assertEqual({e["kind"]: e["line"] for e in v["events"]}, {"call": 4, "base": 3, "return": 4})
        self.assertEqual(v["calls"], 15)
        json.dumps(v)

    def test_the_tree_is_laid_out_in_the_picture(self):
        nodes = self.props(PLAIN, REC)["viz"]["nodes"]
        self.assertEqual(nodes[0]["y"], 0.0)
        self.assertTrue(all(0 <= n["x"] <= 1 and 0 <= n["y"] <= 1 for n in nodes))
        self.assertEqual(nodes[0]["label"], "f(5)")

    def test_a_table_carries_its_cells(self):
        v = self.props(TABLED, TABLE)["viz"]
        self.assertEqual([c["value"] for c in v["cells"]], [1, 1, 2, 3, 5, 8])
        self.assertEqual((v["combine"], v["cells"][0]["line"], v["cells"][2]["line"]), ("sum", 2, 4))

    def test_it_is_drawn_by_remotion_and_a_short_is_dark_blue(self):
        self.assertEqual(hf.engine_for({"layout": "codeviz"}), "remotion")
        self.assertEqual(looks.theme(None, "short")["name"], "neon")

    def test_a_short_scene_stays_up_until_its_picture_has_run(self):
        scene = {"layout": "codeviz", "on_screen": "Plain recursion", "narration": "Watch the tree grow.", "code": REC, "language": "python", "items": [], "viz": PLAIN, "seconds": 3}
        props, lengths = rm.build_props([scene], "short", None, look="neon")
        self.assertGreaterEqual(lengths[0], codeviz.min_seconds(PLAIN))
        self.assertAlmostEqual(props["scenes"][0]["seconds"], lengths[0], places=2)
        times = [e["t"] for e in props["scenes"][0]["viz"]["events"]]
        self.assertGreater(times[1] - times[0], 0.25)   # a pace the viewer can follow

    def test_a_codeviz_scene_needs_words_for_its_picture(self):
        spec = platforms.video_spec({"video": {"format": "short", "target_seconds": 90, "renderer": "remotion", "outro": OUTRO}})
        scene = {"layout": "codeviz", "part": "idea", "narration": "Watch the tree grow.", "on_screen": "Plain recursion", "items": [], "code": REC, "language": "python",
                 "nodes": [], "edges": [], "cells": [], "steps": [], "seconds": 0, "viz": PLAIN}
        got = checks.script_problems(finish({"title": "Climbing stairs, step by step", "description": "x" * 60, "tags": ["a", "b", "c"], "thumbnail_text": "Stairs", "scenes": [scene]}),
                                     spec, {"id": "s", "label": "Short", "kicker": "S"}, {})
        self.assertTrue(any("at least 28 words" in p for p in got))

    def test_words_only_scenes_are_split_in_two_at_most(self):
        intro = {"layout": "title", "part": "intro", "narration": "Have you ever written a function that works for five and then crawls for bigger numbers? Picture a library at the top of a staircase climbed one or two steps at a time. We will solve it three ways, slowly, and watch what each one does."}
        out = checks.split_long_scenes([intro], {"format": "short", "wps": 2.5})
        self.assertLessEqual(len(out), 2)
        self.assertEqual(" ".join(sc["narration"] for sc in out), intro["narration"])

    def test_the_storyboard_artist_never_redraws_it(self):
        scenes = [{"layout": "codeviz", "part": "idea", "narration": "x", "viz": PLAIN, "code": REC, "on_screen": "Plain recursion", "items": [], "nodes": [], "edges": [], "cells": [], "steps": [], "language": "python"}]
        class Ctx:
            video = {"format": "short", "wps": 2.5}
            cat = {}
            profile = {}
        changed = GraphicsAgent()._apply(Ctx, {"scenes": scenes}, scenes, [{"scene": 1, "why": "x", "layout": "statement", "on_screen": "Other", "items": [], "nodes": [], "edges": [],
                                                                         "code": "", "language": "", "cells": [], "steps": [], "clip": ""}])
        self.assertEqual((changed, scenes[0]["layout"]), ([], "codeviz"))


if __name__ == "__main__":
    unittest.main()
