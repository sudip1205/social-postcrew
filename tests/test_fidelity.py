import unittest

from postcrew import fidelity
from postcrew.checks import fidelity_problems


def step(say, active=(), found=(), note="", memo=()):
    return {"say": say, "pointers": [], "active": list(active), "found": list(found), "out": [], "note": note, "memo": list(memo)}


TEN = ["1", "2", "3", "1", "2", "3", "1", "2", "3", "1"]


class FidelityTest(unittest.TestCase):
    def test_a_count_that_jumps_is_sent_back(self):
        # the Subarray Sum Short at 2:39: "count eight" over three steps (1, 5, 8)
        sc = {"layout": "trace", "cells": TEN, "narration": "Watch a ten box shelf, window three, target six, slide on, end at count eight.",
              "steps": [step("ten box shelf", [0, 1, 2], [0, 1, 2], "1 + 2 + 3 = 6", ["count = 1"]),
                        step("slide on", [4, 5, 6], [4, 5, 6], "2 + 3 + 1 = 6", ["count = 5"]),
                        step("count eight", [7, 8, 9], [7, 8, 9], "", ["count = 8"])]}
        self.assertIn("count jumps from 1 to 5", fidelity_problems([sc])[0])

    def test_every_window_counted_passes(self):
        cells = ["2", "2", "1", "3", "2"]
        sums = [(0, 1, 4, 1), (1, 2, 3, 1), (2, 3, 4, 2), (3, 4, 5, 2)]
        sc = {"layout": "trace", "cells": cells, "narration": "The first pair, two plus two, adds to four: a match. The next three, two plus one, is no match. Then four, one plus three, matches again. Then five, three plus two, does not, so the count reaches two.",
              "steps": [step(w, [a, b], [a, b] if s == 4 else [], f"{cells[a]} + {cells[b]} = {s}", [f"count = {c}"])
                        for w, (a, b, s, c) in zip(["first pair", "next three", "then four", "then five"], sums)]}
        self.assertEqual(fidelity_problems([sc]), [])

    def test_a_stated_total_without_counting_is_sent_back(self):
        sc = {"layout": "trace", "cells": ["2", "2", "1", "3", "2"], "narration": "Array minus window plus one windows.",
              "steps": [step("Array minus window", [0, 1], memo=["windows = 4"]), step("plus one", [3, 4], memo=["windows = 4"])]}
        self.assertIn("windows jumps at 4", fidelity_problems([sc])[0])

    def test_count_carries_on_from_the_scene_before(self):
        cells = ["2", "2", "1", "3", "2"]
        a = {"layout": "trace", "cells": cells, "narration": "first pair, next pair", "steps": [step("first pair", memo=["count = 1"]), step("next pair", memo=["count = 2"])]}
        b = {"layout": "trace", "cells": cells, "narration": "then the third", "steps": [step("third", memo=["count = 3"]), step("third", memo=["count = 3"])]}
        self.assertEqual(fidelity_problems([a, b]), [])

    def test_wrong_sums_and_wrong_boxes(self):
        self.assertIn("which is wrong", fidelity.sum_problems(["1", "2"], [step("x", [0, 1], note="1 + 2 = 4")])[0])
        self.assertIn("lit boxes (0, 1, 2) hold 1, 2, 1", fidelity.sum_problems(["1", "2", "1"], [step("x", [0, 1, 2], note="1 + 2 + 3 = 6")])[0])
        self.assertEqual(fidelity.sum_problems(["4", "1", "2"], [step("x", [1, 2], note="4 + 1 - 2 = 3")]), [])

    def test_the_boxes_the_voice_names_are_drawn(self):
        sc = {"layout": "trace", "cells": ["1", "2", "1"], "narration": "Watch a ten box shelf with a window of three boxes.", "steps": [step("ten box"), step("window")]}
        self.assertIn("'ten box' but 3 boxes", fidelity.narration_problems(sc)[0])
        sc["cells"] = TEN
        self.assertEqual(fidelity.narration_problems(sc), [])

    def test_the_said_count_is_the_shown_count(self):
        sc = {"layout": "trace", "cells": TEN, "narration": "and the count reaches eight.", "steps": [step("count", memo=["count = 1"]), step("eight", memo=["count = 2"])]}
        self.assertIn("count is 8 but the last step shows count = 2", fidelity.narration_problems(sc)[0])

    def test_steps_are_cued_on_the_narration(self):
        sc = {"narration": "Neighbouring windows share boxes.", "steps": [step("Neighbouring windows"), step("and the count")]}
        self.assertIn("not in the narration", fidelity.cue_problems(sc)[0])

    def test_numbers_in_words(self):
        self.assertEqual([fidelity.number(w) for w in ("eight", "twenty-one", "12", "ninety", "box")], [8, 21, 12, 90, None])


if __name__ == "__main__":
    unittest.main()


class PaceAndCodeTest(unittest.TestCase):
    # the Kadane Short: five steps in one 22-word sentence at 1:59, "brute force takes n cubed" over a two-loop brute.py, three ways promised
    # and two coded
    def test_a_rushed_walk_through_is_sent_back(self):
        sc = {"layout": "trace", "cells": ["-2", "1", "-3", "4", "-1"], "narration": "It starts at minus two, restarts at one, dips to minus two, restarts at four, then grows to three.",
              "steps": [step(w) for w in ("starts at minus two", "restarts at one", "dips to minus two", "restarts at four", "grows to three")]}
        self.assertIn("5 steps in 19 words", fidelity.pace_problems(sc)[0])

    def test_complexity_said_matches_the_code(self):
        brute = "for i in range(n):\n    total = 0\n    for j in range(i, n):\n        total += a[j]\n"
        kadane = "for x in a:\n    cur = max(x, cur + x)\n"
        scenes = [{"layout": "points", "narration": "Plain brute force takes n cubed time, prefix sums take n squared, and Kadane takes just O of n.", "items": []},
                  {"layout": "code", "on_screen": "brute.py", "code": brute, "narration": "First brute force."},
                  {"layout": "code", "on_screen": "kadane.py", "code": kadane, "narration": "Now Kadane, one pass, O of n."}]
        out = fidelity.code_problems(scenes)
        self.assertEqual(len(out), 1)
        self.assertIn("says brute takes n³ time", out[0])
        scenes[0]["narration"] = "We have three ways. Brute force takes n squared and Kadane takes O of n."
        self.assertIn("promises 3 ways but code is shown for 2", fidelity.code_problems(scenes)[0])
        scenes[0]["narration"] = "We have two ways. Brute force takes n squared, and Kadane carries one number in O of n."
        self.assertEqual(fidelity.code_problems(scenes), [])

    def test_loops_and_complexity_words(self):
        self.assertEqual(fidelity.loop_depth("for i in a:\n    for j in a:\n        for k in a:\n            pass\nfor z in a:\n    pass"), 3)
        self.assertEqual([fidelity.complexities(t) for t in ("carries one number", "O(n^2)", "n cubed", "O of n log n")], [[], [2], [3], []])


class SteadyPictureTest(unittest.TestCase):
    def test_a_diagram_growing_over_scenes_keeps_one_layout(self):
        from postcrew.render.remotion import _steady_diagrams, _continue_code
        box = lambda *ls: [{"label": l} for l in ls]
        e = lambda a, b: {"from": a, "to": b}
        scenes = [{"layout": "diagram", "nodes": box("Array", "Brute", "Kadane"), "edges": [e(0, 1)]},
                  {"layout": "diagram", "nodes": box("Array", "Brute", "Kadane"), "edges": [e(0, 1), e(0, 2)]},
                  {"layout": "code", "code": "x", "items": ["$ run", "6"]}, {"layout": "code", "code": "x", "items": ["$ run", "6"]}]
        _steady_diagrams(scenes)
        _continue_code(scenes)
        self.assertEqual([(x["from"], x["to"]) for x in scenes[0]["layout_edges"]], [(0, 1), (0, 2)])
        self.assertEqual(scenes[0]["layout_edges"], scenes[1]["layout_edges"])
        self.assertEqual((scenes[2]["items"], scenes[3].get("typed")), ([], True))


class DiagramCarryTest(unittest.TestCase):
    def test_a_new_diagram_does_not_inherit_the_last_ones_boxes(self):
        from postcrew.render.remotion import build_props
        a = {"layout": "diagram", "narration": "Five numbers gave fifteen runs.", "on_screen": "Repeated work", "nodes": ["5 numbers", "15 runs"], "edges": ["5 numbers > 15 runs"]}
        b = {"layout": "diagram", "narration": "Brute force or Kadane.", "on_screen": "Two ways", "nodes": ["Array", "Brute force", "Kadane"], "edges": ["Array > Brute force", "Array > Kadane"]}
        c = dict(b, nodes=["Array", "Brute force", "Kadane", "Prefix"], edges=["Array > Prefix"])
        props, _ = build_props([a, b, c], "short", None)
        self.assertEqual([x["label"] for x in props["scenes"][1]["nodes"]], ["Array", "Brute force", "Kadane"])
        self.assertEqual(len(props["scenes"][2]["nodes"]), 4)   # the same picture growing keeps its boxes


class WorkedNumbersTest(unittest.TestCase):
    """2026-11-06, Diffie-Hellman: "2^5 = 32 = 6" on an arrow and "216 mod 13 = 8" in one trace step; the viewer paused three times."""

    def test_a_calculation_typed_on_a_picture_must_be_run(self):
        from postcrew.checks import worked_numbers_problems as w
        self.assertTrue(w([{"layout": "diagram", "edges": ["Secret > Public: 2^5 = 32 = 6"], "narration": "Bob keeps a secret five."}]))
        self.assertTrue(w([{"layout": "trace", "cells": ["216", "8"], "steps": [{"note": "216 mod 13 = 8"}], "narration": "It wraps."}]))
        self.assertTrue(w([{"layout": "diagram", "narration": "Raising two to the fifth gives thirty two, which wraps around to six."}]))
        fine = [{"layout": "points", "items": ["Public: 13, 2, 8, 6"], "narration": "Eve sees thirteen, two, eight and six."},
                {"layout": "stat", "items": ["2048 bits"], "narration": "Real keys use a prime of at least 2048 bits."},
                {"layout": "run", "narration": "Two times sixteen is thirty two, which wraps around the clock."}]
        self.assertEqual(w(fine), [])

    def test_a_run_shows_each_wrap_as_mod_and_its_list_may_start_with_one_value(self):
        from postcrew import algotrace
        code = ("def public_number(g, secret, p):\n    x = 1\n    powers = [1]\n    for turn in range(secret):\n        x = x * g\n"
                "        x = x % p   # step\n        powers.append(x)\n    return x\n")
        notes = [n for st in algotrace.run(code, "public_number(2, 5, 13)")["steps"] for n in st.get("notes") or []]
        self.assertIn("x = 8 * 2 = 16", notes)
        self.assertIn("x = 16 mod 13 = 3", notes)
        sc = {"layout": "run", "code": code, "narration": " ".join(["Each step is said in one full sentence here."] * 6),
              "run": {"call": "public_number(2, 5, 13)", "kind": "array", "array": "powers", "pointers": [], "window": [],
                      "show": ["x"], "steps": "1-6"}}
        self.assertEqual(algotrace.problems(sc, 1), [])
