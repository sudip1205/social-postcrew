"""The Remotion renderer: it is registered and is the default, and the props it hands the React project carry the voice's timing."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from helpers import TempWorkspace  # noqa: E402

from postcrew import defaults, platforms  # noqa: E402
from postcrew.agents.supervisor import crew_for  # noqa: E402
from postcrew.render import remotion as rm  # noqa: E402

SCENES = [
    {"layout": "diagram", "on_screen": "Path", "nodes": ["Client", "Server"], "edges": ["Client > Server: GET /a"],
     "narration": "The client sends get a to the server."},
    {"layout": "trace", "on_screen": "Walk", "cells": ["2", "7"], "narration": "Left starts at zero then moves right.",
     "steps": [{"say": "left", "pointers": ["left=0"], "note": "2"}, {"say": "right", "pointers": ["left=1"], "note": "7"}]},
]


class RemotionTests(unittest.TestCase):
    def test_it_is_the_default_renderer(self):
        self.assertEqual(defaults.DEFAULT_CONFIG["platforms"]["youtube"]["video"]["renderer"], "remotion")

    def test_props_carry_times_and_the_scene_lengths(self):
        props, lengths = rm.build_props(SCENES, "long", None)
        self.assertEqual((props["width"], props["height"]), (1920, 1080))
        self.assertEqual(len(props["scenes"]), 2)
        d = props["scenes"][0]
        self.assertEqual(d["edges"][0]["label"], "GET /a")
        self.assertTrue(all(n["t"] is not None for n in d["nodes"]))
        steps = props["scenes"][1]["steps"]
        self.assertLessEqual(steps[0]["t"], steps[1]["t"])
        self.assertEqual(steps[1]["pointers"], [{"name": "left", "at": 1}])
        self.assertAlmostEqual(sum(lengths), sum(s["seconds"] for s in props["scenes"]), places=2)

    def test_captions_cover_the_narration(self):
        props, _ = rm.build_props(SCENES[:1], "short", None)
        self.assertEqual(" ".join(c["text"] for c in props["scenes"][0]["captions"]), SCENES[0]["narration"])

    def test_words_go_to_hyperframes_and_data_to_remotion(self):
        from postcrew.render import hyperframes as hf
        scenes = [{"layout": "title"}, {"layout": "statement"}, {"layout": "diagram"}, {"layout": "trace"}, {"layout": "statement"}]
        self.assertEqual([hf.engine_for(s) for s in scenes], ["hyperframes", "hyperframes", "remotion", "remotion", "hyperframes"])

    def test_three_steps_replace_the_video_producer(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"]["video"]["renderer"] = "remotion"
            ws.save_config(cfg)
            view = platforms.view(ws.config(), "youtube")
            ids = [a.id for a in crew_for("youtube", view, None)]
            self.assertEqual(ids[ids.index("voice") + 1:ids.index("voice") + 4], ["text_frames", "data_frames", "media"])

    def test_each_engine_draws_its_own_scenes(self):
        from postcrew.agents.base import RunContext
        from postcrew.agents.frames import HyperFramesAgent, RemotionFramesAgent
        scenes = [{"layout": "title"}, {"layout": "diagram"}, {"layout": "statement"}, {"layout": "points"}]
        ctx = RunContext(ws=None, cfg={}, day=None, category="", run=None, llm=None, outputs={"writer": {"scenes": scenes}})
        self.assertEqual(HyperFramesAgent().mine(ctx, scenes), [0, 2])
        self.assertEqual(RemotionFramesAgent().mine(ctx, scenes), [1, 3])
        ctx.outputs["text_frames"] = {"scenes": [0, 2]}
        self.assertEqual(RemotionFramesAgent().mine(ctx, scenes), [1, 3])

    def test_the_hyperframes_scene_is_timed_to_the_voice_and_has_no_watermark(self):
        from postcrew.render import hyperframes as hf
        props, _ = rm.build_props([{"layout": "title", "on_screen": "A <b> title", "narration": "Hello there friend."}], "short", None)
        page = hf.scene_html(props["scenes"][0], 1080, 1920)
        self.assertIn('data-width="1080"', page)
        self.assertIn(f'data-duration="{props["scenes"][0]["seconds"]:.3f}"', page)
        self.assertIn("&lt;b&gt;", page)
        self.assertIn('window.__timelines["scene"]', page)
        self.assertNotIn("POSTCREW", page.upper().replace("POSTCREW SCENE", ""))   # only the page title, no brand text on the picture
        src = (Path(__file__).parent.parent / "postcrew" / "remotion" / "src" / "Video.tsx").read_text()
        self.assertNotIn("p.kicker", src)
        self.assertNotIn("p.handle", src)

if __name__ == "__main__":
    unittest.main()
