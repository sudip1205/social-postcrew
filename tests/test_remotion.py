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
    def test_a_look_is_off_white_or_black_with_one_accent(self):
        from postcrew.render import looks
        self.assertEqual(looks.theme("ink")["name"], "ink")
        self.assertEqual(looks.theme("neon", "short")["name"], "paper")   # an unknown look is chosen by the format
        self.assertEqual(looks.theme(None, "long")["name"], "ink")
        for name, t in looks.LOOKS.items():
            r, g, b = (int(t["bg"][i:i + 2], 16) for i in (1, 3, 5))
            self.assertFalse(b > r + 25 and b > g + 10, f"{name}: the page must not be blue")     # no blue backgrounds
            self.assertEqual(len({k for k in t if k.startswith("accent") and k != "accentSoft"}), 1)   # one accent colour

    def test_the_palette_is_blue_orange_and_green_and_the_look_follows_the_format(self):
        from postcrew import platforms
        from postcrew.render import looks
        p, k = looks.LOOKS["paper"], looks.LOOKS["ink"]
        self.assertEqual((p["accent"], p["highlight"], p["positive"], p["text"]), ("#279CF5", "#FA7900", "#068200", "#424242"))   # on white
        self.assertEqual((k["accent"], k["highlight"], k["text"]), ("#24C1FF", "#FA7900", "#C7C7C7"))                              # on black
        self.assertEqual(k["positive"], "#FA7900")      # there is no green on black: what was found is orange
        self.assertEqual((looks.resolve("auto", "short"), looks.resolve("auto", "long")), ("paper", "ink"))   # white vertical, black wide
        self.assertEqual((looks.resolve("ink", "short"), looks.resolve("paper", "long")), ("ink", "paper"))  # unless chosen
        self.assertEqual(looks.resolve("neon", "long"), "ink")
        base = {"video": {"format": "short", "look": "auto"}}
        self.assertEqual(platforms.video_spec(base)["look"], "paper")
        self.assertEqual(platforms.video_spec(base, {"format": "long"})["look"], "ink")
        self.assertEqual(platforms.video_spec({"video": {"format": "long", "look": "paper"}})["look"], "paper")
        props, _ = rm.build_props([{"layout": "title", "on_screen": "x", "narration": "Hello."}], "long", None)
        self.assertEqual(props["theme"]["name"], "ink")

    def test_the_theme_goes_with_the_props_and_into_the_scene(self):
        from postcrew.render import hyperframes as hf
        props, _ = rm.build_props([{"layout": "title", "on_screen": "Calm intro", "narration": "Hello there."}], "short", None, "ink")
        self.assertEqual(props["theme"]["name"], "ink")
        page = hf.scene_html(props["scenes"][0], 1080, 1920, props["theme"])
        self.assertIn(props["theme"]["bg"], page)
        self.assertNotIn("radial-gradient", page)                          # no coloured or animated background
        self.assertNotIn("blur(", page)
        self.assertIn("@font-face", page)

    def test_the_closing_scene_comes_in_after_one_second_of_silence(self):
        from postcrew.render import video
        scenes = [{"layout": "statement", "on_screen": "A point", "narration": "A point to remember."},
                  {"layout": "statement", "on_screen": "Like \u00b7 Comment \u00b7 Share",
                   "narration": "Please like, comment and share it with someone who would find it helpful."}]
        plain, plain_len = rm.build_props([dict(s) for s in scenes], "short", None)
        rm.mark_closing(scenes, {"outro": "Please like, comment and share."})
        self.assertTrue(scenes[-1]["closing"] and "closing" not in scenes[0])
        props, lengths = rm.build_props(scenes, "short", None)
        self.assertAlmostEqual(lengths[1] - plain_len[1], video.LEAD_S, places=2)      # the pause is part of the scene
        self.assertAlmostEqual(lengths[0] - plain_len[0], video.OPEN_S, places=2)      # the opening picture is up before the voice
        self.assertGreaterEqual(props["scenes"][0]["captions"][0]["start"], video.OPEN_S)
        last = props["scenes"][1]
        self.assertGreaterEqual(last["captions"][0]["start"], video.LEAD_S)             # nothing is said before it
        self.assertEqual(last["items"], ["Like", "Comment", "Share"])
        self.assertEqual(len(last["cues"]), 3)
        self.assertTrue(all(c >= video.LEAD_S for c in last["cues"]) and last["cues"] == sorted(last["cues"]))
        self.assertTrue(last["closing"] and "closing" not in props["scenes"][0])

    def test_no_closing_scene_without_a_closing_line(self):
        scenes = rm.mark_closing([{"layout": "statement", "narration": "x"}], {"outro": ""})
        self.assertNotIn("closing", scenes[0])

    def test_the_thumbnail_picture_is_drawn_from_the_videos_own_content(self):
        script = {"title": "Circuit Breaker Pattern Explained: Stop Cascading Failures", "thumbnail_text": "Stop cascading failures", "scenes": [
            {"layout": "statement", "on_screen": "x"},
            {"layout": "flow", "nodes": ["Client", "Circuit Breaker|gateway", "Payments API"], "edges": []}]}
        pic = rm.illustration(script)
        self.assertEqual((pic["kind"], pic["nodes"], pic["focus"]), ("diagram", ["Client", "Circuit Breaker", "Payments API"], 1))   # the box named in the title
        trace = {"title": "Two Sum", "scenes": [{"layout": "trace", "cells": ["2", "7", "11"], "steps": [{"found": []}, {"found": [0, 1]}]}]}
        self.assertEqual(rm.illustration(trace), {"kind": "trace", "cells": ["2", "7", "11"], "found": [0, 1]})
        code = {"title": "T", "scenes": [{"layout": "code", "code": "def f():\n    return 1\n"}]}
        self.assertEqual(rm.illustration(code)["kind"], "code")
        self.assertIsNone(rm.illustration({"title": "T", "scenes": [{"layout": "statement"}, {"layout": "points", "items": ["a"]}]}))
        self.assertEqual(rm.illustration({"title": "Plain", "scenes": [{"layout": "diagram", "nodes": ["A", "B", "C"]}]})["focus"], 1)   # no match: the middle

    def test_the_highlighted_word_can_be_chosen_with_asterisks(self):
        from postcrew.render import hyperframes as hf
        self.assertEqual(rm._marked("Welcome to Dip to *Dive*"), ("Welcome to Dip to Dive", 4))
        self.assertEqual(rm._marked("No marker here"), ("No marker here", None))
        props, _ = rm.build_props([{"layout": "title", "on_screen": "Welcome to Dip to *Dive*", "narration": "Hi."}], "long", None)
        sc = props["scenes"][0]
        self.assertEqual((sc["title"], sc["key"]), ("Welcome to Dip to Dive", 4))
        page = hf.scene_html(sc, 1920, 1080, props["theme"])
        self.assertEqual(page.count(' key"'), 1)
        self.assertIn('<span class="m key"><span class="w">Dive</span>', page)          # Dive, not the longest word (Welcome)


if __name__ == "__main__":
    unittest.main()
