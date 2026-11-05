"""Run the code, draw what happened: every step on the board is the code's real step."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from postcrew import algotrace  # noqa: E402
from postcrew.render import timeline  # noqa: E402

KADANE = '''def max_subarray(nums):
    current = best = nums[0]
    for i in range(1, len(nums)):
        current = max(nums[i], current + nums[i])
        best = max(best, current)  # step
    return best
'''
RUN = {"call": "max_subarray([-2, 1, -3, 4, -1])", "kind": "array", "array": "nums", "pointers": ["i"], "window": [], "show": ["current", "best"],
       "steps": "2-5"}
GOOD = ("Day two: one alone beats minus two plus one, so current is one. "
        "Day three: one minus three is minus two, best stays one. "
        "Day four: four alone beats minus two plus four, so current is four. "
        "Day five: four minus one is three, best stays four.")


class AlgoTraceTest(unittest.TestCase):
    def test_the_real_steps_and_their_calculations_are_recorded(self):
        out = algotrace.run(KADANE, RUN["call"])
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["steps"][0]["start"])   # what the loop starts from is the first step
        self.assertEqual((out["steps"][0]["vars"]["current"], out["steps"][0]["vars"]["best"]), (-2, -2))
        self.assertEqual([(s["vars"]["i"], s["vars"]["current"], s["vars"]["best"]) for s in out["steps"][1:]], [(1, 1, 1), (2, -2, 1), (3, 4, 4), (4, 3, 4)])
        self.assertIn("current = max(4, -2 + 4) = 4", out["steps"][3]["notes"])
        self.assertIn("current = max(-3, 1 - 3) = -2", out["steps"][2]["notes"])

    def test_a_scene_is_drawn_from_the_run(self):
        sc = {"layout": "run", "code": KADANE, "run": RUN, "narration": GOOD, "on_screen": "Kadane"}
        self.assertEqual(algotrace.problems(sc, 3), [])
        p = algotrace.props(sc, timeline.word_times(GOOD, 16.0))
        self.assertEqual(p["layout"], "trace")
        self.assertEqual(p["cells"], ["-2", "1", "-3", "4", "-1"])
        self.assertEqual([s["pointers"][0]["at"] for s in p["steps"]], [1, 2, 3, 4])
        self.assertEqual(p["steps"][2]["memo"], ["current = 4", "best = 4"])
        times = [s["t"] for s in p["steps"]]
        self.assertEqual(times, sorted(times))
        self.assertGreater(times[1] - times[0], 2.0)   # each step waits for its own sentence

    def test_the_narration_must_follow_the_real_steps(self):
        sc = {"layout": "run", "code": KADANE, "run": RUN, "narration": "It goes one, minus two, four, three."}
        msg = algotrace.problems(sc, 3)[0]
        self.assertIn("1 sentence(s) but the scene shows 4 step(s)", msg)
        self.assertIn("current = max(4, -2 + 4) = 4", msg)   # the writer is given the real steps
        self.assertIn("no such variable", algotrace.problems(dict(sc, run=dict(RUN, show=["sum"])), 3)[0])
        self.assertIn("'# step'", algotrace.problems(dict(sc, code=KADANE.replace("  # step", "")), 3)[0])
        self.assertIn("failed", algotrace.problems(dict(sc, run=dict(RUN, call="max_subarray(nope)")), 3)[0])

    def test_the_code_runs_locked_down(self):
        self.assertIn("not allowed", algotrace.run("import os\ndef f():\n    os.system('true')  # step\n", "f()")["error"])
        self.assertIn("not allowed", algotrace.run("def f():\n    open('/tmp/x', 'w')  # step\n", "f()")["error"])
        self.assertFalse(algotrace.run("def f():\n    while True:\n        pass  # step\n", "f()")["ok"])

    def test_algorithm_mode_refuses_hand_written_steps(self):
        from postcrew.agents.script import algorithm_problems
        run = {"layout": "run", "code": KADANE, "run": RUN}
        hand = {"layout": "trace", "cells": ["1", "2"], "steps": [{"say": "x"}]}
        self.assertIn("scene(s) 2", algorithm_problems({"scenes": [run, hand]})[0])
        self.assertEqual(algorithm_problems({"scenes": [run, dict(run)]}), [])

    def test_the_plan_box_reaches_the_crew(self):
        from helpers import TempWorkspace
        from postcrew import monthly
        from postcrew.agents import planner
        with TempWorkspace() as ws:
            it = monthly.add_manual(ws, "youtube", "Maximum subarray", "Kadane", algorithm=True)
            self.assertTrue(it["algorithm"])
            from datetime import date
            monthly.run_plan(ws, "youtube", it["id"], "short", today=date(2026, 11, 4))
            self.assertTrue(planner.load_plan(ws, "youtube")["2026-11-04"]["algorithm"])


if __name__ == "__main__":
    unittest.main()


class AlgorithmOrderTest(unittest.TestCase):
    # the first algorithm-mode run taught Kadane with hand-drawn diagrams ("adding gives one, so we start fresh") before brute force had run
    def test_the_simple_way_runs_first_and_calculations_are_run(self):
        from postcrew.agents.script import algorithm_problems
        brute = "def f(a):\n    best = a[0]\n    for i in range(len(a)):\n        for j in range(i, len(a)):\n            best = max(best, sum(a[i:j + 1]))  # step\n    return best\n"
        fast = {"layout": "run", "part": "idea", "code": KADANE, "run": RUN}
        slow = {"layout": "run", "part": "visual", "code": brute, "run": RUN}
        told = {"layout": "diagram", "part": "visual", "narration": "On day two, adding gives one, so the larger of three or one is three."}
        out = algorithm_problems({"scenes": [told, fast, slow]})
        self.assertTrue(any("narrate calculations" in p for p in out))
        self.assertTrue(any("runs a faster way before the simple one" in p for p in out))
        self.assertTrue(any("teach the idea before any code has run" in p for p in out))
        self.assertEqual(algorithm_problems({"scenes": [slow, fast]}), [])
