"""The staircase scene: the app finds every way up, so the count drawn is always right."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from postcrew import checks, pathviz, platforms  # noqa: E402
from postcrew.agents.graphics import GraphicsAgent  # noqa: E402
from postcrew.agents.script import SCHEMA, finish  # noqa: E402
from postcrew.render import hyperframes as hf, remotion as rm  # noqa: E402

OUTRO = "If this was useful, please like, comment and subscribe. And if you liked it, share it with someone who would find it helpful."
V = {"kind": "stairs", "title": "3 steps, how many ways?", "n": 3, "moves": [1, 2]}


class EveryWayUp(unittest.TestCase):
    def test_the_counts_are_the_climbing_stairs_numbers(self):
        self.assertEqual([len(pathviz.enumerate_paths(n, [1, 2])) for n in range(1, 7)], [1, 2, 3, 5, 8, 13])

    def test_the_ways_are_listed_shortest_hops_first(self):
        self.assertEqual(pathviz.enumerate_paths(3, [1, 2]), [[1, 1, 1], [1, 2], [2, 1]])
        self.assertEqual(pathviz.enumerate_paths(4, [1, 2, 3])[:3], [[1, 1, 1, 1], [1, 1, 2], [1, 2, 1]])

    def test_other_hops_work_too(self):
        self.assertEqual(len(pathviz.enumerate_paths(4, [1, 3])), 3)    # 1111, 13, 31


class TheChecks(unittest.TestCase):
    def test_a_good_staircase_passes(self):
        self.assertEqual(pathviz.problems(V, 3), [])
        self.assertEqual(pathviz.problems(dict(V, n=5), 3), [])

    def test_the_size_is_limited_so_every_way_can_be_seen(self):
        self.assertTrue(any("paths.n" in p for p in pathviz.problems(dict(V, n=9), 3)))
        self.assertTrue(any("more than" in p for p in pathviz.problems(dict(V, n=6, moves=[1, 2, 3]), 3)))
        self.assertTrue(pathviz.problems(dict(V, moves=[]), 3))
        self.assertTrue(pathviz.problems(dict(V, moves=[1, 1]), 3))
        self.assertTrue(pathviz.problems({}, 3))

    def test_the_scene_in_a_script(self):
        spec = platforms.video_spec({"video": {"format": "short", "target_seconds": 90, "renderer": "remotion", "outro": OUTRO}})
        scene = {"layout": "paths", "part": "visual", "narration": "Three steps. One hop of one, then another, then another. That is one way.", "on_screen": "Three steps",
                 "items": [], "code": "", "language": "", "nodes": [], "edges": [], "cells": [], "steps": [], "seconds": 0, "paths": V}
        script = lambda sc: finish({"title": "Climbing stairs, step by step", "description": "x" * 60, "tags": ["a", "b", "c"], "thumbnail_text": "Stairs", "scenes": [sc]})
        got = checks.script_problems(script(scene), spec, {"id": "s", "label": "Short", "kicker": "S"}, {})
        self.assertFalse([p for p in got if "scene 1:" in p and "paths" in p], got)
        bad = checks.script_problems(script(dict(scene, paths=dict(V, n=9))), spec, {"id": "s", "label": "Short", "kicker": "S"}, {})
        self.assertTrue(any("paths.n" in p for p in bad))

    def test_the_writer_may_answer_with_one(self):
        scene = SCHEMA["properties"]["scenes"]["items"]
        self.assertIn("paths", scene["properties"]["layout"]["enum"])
        self.assertEqual(scene["properties"]["paths"], pathviz.PATHS)
        self.assertNotIn("paths", scene["required"])
        self.assertIn("visual", scene["properties"]["part"]["enum"])


class TheProps(unittest.TestCase):
    def props(self, v, seconds=12):
        sc = {"layout": "paths", "on_screen": "Three steps", "narration": "One hop, then another. " * 4, "items": [], "paths": v, "seconds": seconds}
        out, lengths = rm.build_props([sc], "short", None, look="neon")
        return out["scenes"][0], lengths[0]

    def test_every_way_has_a_time_in_order(self):
        scene, _ = self.props(dict(V, n=5))
        p = scene["paths"]
        self.assertEqual(len(p["paths"]), 8)
        times = [x["t"] for x in p["paths"]]
        self.assertEqual(times, sorted(times))
        self.assertEqual(p["paths"][1]["label"], "1 + 1 + 1 + 2")
        json.dumps(p)

    def test_the_scene_stays_up_until_every_way_has_been_shown(self):
        scene, length = self.props(dict(V, n=5), seconds=3)
        self.assertGreaterEqual(length, pathviz.min_seconds(dict(V, n=5)))
        self.assertLess(scene["paths"]["paths"][-1]["t"] + scene["paths"]["per"], scene["seconds"])

    def test_it_is_drawn_by_remotion_and_never_redrawn_by_the_artist(self):
        self.assertEqual(hf.engine_for({"layout": "paths"}), "remotion")
        scenes = [{"layout": "paths", "part": "visual", "narration": "x", "paths": V, "on_screen": "Three steps", "items": [], "nodes": [], "edges": [], "cells": [], "steps": [], "code": "", "language": ""}]

        class Ctx:
            video = {"format": "short", "wps": 2.5}
            cat = {}
            profile = {}
        changed = GraphicsAgent()._apply(Ctx, {"scenes": scenes}, scenes, [{"scene": 1, "why": "x", "layout": "statement", "on_screen": "Other", "items": [], "nodes": [], "edges": [],
                                                                         "code": "", "language": "", "cells": [], "steps": [], "clip": ""}])
        self.assertEqual((changed, scenes[0]["layout"]), ([], "paths"))


if __name__ == "__main__":
    unittest.main()
