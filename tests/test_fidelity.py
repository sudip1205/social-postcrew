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
