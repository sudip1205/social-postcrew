"""Icons and cliparts: the catalog, the props the renderer draws from, and the Storyboard Artist."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_youtube_crew as yc  # noqa: E402
from helpers import ScriptedLLM, TempWorkspace  # noqa: E402
from postcrew.agents.graphics import GraphicsAgent, with_icon  # noqa: E402
from postcrew.render import hyperframes as hf, iconlib, remotion as rm  # noqa: E402
from postcrew.crew import run_crew  # noqa: E402

HAVE = iconlib.available()


@unittest.skipUnless(HAVE, "the Iconify sets are installed with the Remotion project (npm install)")
class IconLibTests(unittest.TestCase):
    def test_tools_find_their_logo_and_concepts_a_line_icon(self):
        self.assertEqual(iconlib.search("Redis", 1)[0]["id"], "logos:redis")
        self.assertEqual(iconlib.search("PostgreSQL", 1)[0]["id"], "logos:postgresql")
        self.assertEqual(iconlib.search("Load Balancer", 1)[0]["id"], "lucide:network")
        self.assertEqual(iconlib.search("warning", 1)[0]["id"], "fluent-emoji-flat:warning")

    def test_an_icon_is_real_or_it_is_nothing(self):
        self.assertTrue(iconlib.exists("lucide:database"))
        self.assertFalse(iconlib.exists("lucide:no-such-icon-at-all"))
        self.assertFalse(iconlib.exists("someset:database"))
        self.assertIsNone(iconlib.svg("lucide:no-such-icon-at-all"))
        old = iconlib.get("database")                                  # the older one-word hints still work
        self.assertEqual(old["id"], "lucide:database")
        self.assertFalse(old["color"])
        self.assertTrue(iconlib.get("logos:redis")["color"])           # logos keep their own colours

    def test_a_box_gets_an_icon_unless_it_names_one(self):
        self.assertEqual(with_icon("Cache"), "Cache|lucide:zap")
        self.assertEqual(with_icon("Cache|logos:redis"), "Cache|logos:redis")
        self.assertEqual(with_icon("Cache|nonsense:thing"), "Cache|lucide:zap")


@unittest.skipUnless(HAVE, "the Iconify sets are installed with the Remotion project (npm install)")
class RenderPropsTests(unittest.TestCase):
    def test_boxes_and_cliparts_carry_their_svg(self):
        scenes = [{"layout": "diagram", "on_screen": "Path", "narration": "The client calls the cache.", "nodes": ["Client|client", "Cache|logos:redis"],
                   "edges": ["Client > Cache: get"], "items": []},
                  {"layout": "statement", "on_screen": "Careful", "narration": "Watch out.", "clip": "fluent-emoji-flat:warning", "items": []}]
        props, _ = rm.build_props(scenes, "long", None)
        boxes = props["scenes"][0]["nodes"]
        self.assertTrue(all(b["svg"] and b["svg"]["body"] for b in boxes))
        self.assertTrue(boxes[1]["svg"]["color"] and not boxes[0]["svg"]["color"])
        self.assertTrue(props["scenes"][1]["clip"]["body"])
        json.dumps(props)                                              # it is sent to Remotion as JSON

    def test_a_scene_with_a_clipart_is_drawn_by_remotion(self):
        self.assertEqual(hf.engine_for({"layout": "statement"}), "hyperframes")
        self.assertEqual(hf.engine_for({"layout": "statement", "clip": "lucide:timer"}), "remotion")


@unittest.skipUnless(HAVE, "the Iconify sets are installed with the Remotion project (npm install)")
class StoryboardArtistTests(unittest.TestCase):
    def _ctx_run(self, answer):
        with TempWorkspace() as ws:
            yc.youtube_ws(ws)
            cfg = ws.config()
            cfg["platforms"]["youtube"]["video"]["renderer"] = "remotion"
            ws.save_config(cfg)
            s = yc.script()
            writer = yc.finish(s)
            llm = ScriptedLLM({"topic": [yc.topic("Default arguments", ())], "writer": [writer], "editor": [yc.review()], "graphics": [answer]})
            return ws, llm

    def test_the_artist_applies_valid_pictures_and_the_program_fills_in_the_rest(self):
        agent = GraphicsAgent()
        scenes = [{"layout": "title", "part": "intro", "narration": "A rocket launch needs a clear problem.", "on_screen": "Launch"},
                  {"layout": "diagram", "part": "idea", "narration": "The client asks the cache.", "nodes": ["Client", "Cache"], "edges": ["Client > Cache: get"]},
                  {"layout": "statement", "part": "mistake", "narration": "Never trust a warning that is slow.", "on_screen": "Slow warning"},
                  {"layout": "statement", "part": "closing", "narration": "Like and share.", "on_screen": "Like"}]
        boxes, clips = agent._complete(scenes)
        self.assertTrue(all(split_icon for split_icon in (n.split("|")[1] for n in scenes[1]["nodes"])))    # every box has an icon
        self.assertTrue(scenes[0]["clip"] and scenes[2]["clip"])                                              # every words scene has a clipart
        self.assertNotIn("clip", scenes[3])                                                                    # the closing card is left alone
        self.assertEqual((boxes, clips), (2, 2))

    def test_the_report_offers_icons_for_each_box(self):
        scenes = [{"layout": "diagram", "part": "idea", "narration": "The client asks Redis.", "nodes": ["Client", "Redis"], "edges": []}]
        text = GraphicsAgent._report(scenes, {"wps": 2.5})
        self.assertIn("icons for box 'Redis': logos:redis", text)

    def test_the_step_is_skipped_for_slides_and_when_switched_off(self):
        with TempWorkspace() as ws:
            yc.youtube_ws(ws)
            class C:  # noqa: D401
                cfg = ws.config()
                video = {"renderer": "remotion"}
            self.assertTrue(GraphicsAgent().applies(C))
            C.video = {"renderer": "ffmpeg"}
            self.assertFalse(GraphicsAgent().applies(C))
            C.video = {"renderer": "remotion"}
            C.cfg = dict(C.cfg, video={"graphics": False})
            self.assertFalse(GraphicsAgent().applies(C))


if __name__ == "__main__":
    unittest.main()


class SplitLongScenesTests(unittest.TestCase):
    SPEC = {"format": "long", "wps": 2.5}

    def test_a_long_scene_becomes_several_at_its_sentences(self):
        from postcrew.checks import split_long_scenes
        text = " ".join(f"Sentence number {i} says something useful about the design." for i in range(10))
        out = split_long_scenes([{"layout": "diagram", "part": "idea", "narration": text, "nodes": ["A", "B"], "edges": ["A > B: x"], "on_screen": "X"}], self.SPEC)
        self.assertGreater(len(out), 1)
        self.assertEqual(" ".join(s["narration"] for s in out), text)                 # not a word lost or changed
        self.assertTrue(all(len(s["narration"].split()) <= 40 for s in out))
        self.assertEqual(out[0]["edges"], ["A > B: x"])
        self.assertTrue(all(s["nodes"] == ["A", "B"] for s in out))                     # the boxes carry on; the artist draws what each part says

    def test_short_scenes_and_the_closing_card_are_left_alone(self):
        from postcrew.checks import split_long_scenes
        sc = [{"layout": "statement", "part": "idea", "narration": "A short one."}, {"layout": "statement", "part": "closing", "narration": "Like. " * 30}]
        self.assertEqual(split_long_scenes(sc, self.SPEC), sc)

    def test_the_writer_is_not_rejected_for_a_long_scene_when_the_artist_will_split_it(self):
        from postcrew.checks import storyboard_problems
        long = [{"layout": "diagram", "part": "idea", "nodes": ["Client", "Server"], "narration": "The client calls the server. " + "word " * 120}]
        self.assertTrue(any("split it" in p for p in storyboard_problems(long, dict(self.SPEC))))
        self.assertFalse(any("split it" in p for p in storyboard_problems(long, dict(self.SPEC, artist=True))))


class MovingPicturesTests(unittest.TestCase):
    def test_a_box_can_be_down_busy_or_carry_a_count(self):
        from postcrew.render.scenes import node_extra, split_node
        self.assertEqual(split_node("Server 3|lucide:server|down"), ("Server 3", "lucide:server"))        # the icon is still the second part
        self.assertEqual(node_extra("Server 3|lucide:server|down"), ("down", None))
        self.assertEqual(node_extra("Server 2|lucide:server|busy"), ("busy", None))
        self.assertEqual(node_extra("Server A|lucide:server|4"), ("", 4))
        self.assertEqual(node_extra("Server B|lucide:server"), ("", None))
        self.assertEqual(node_extra("Server C|lucide:server|nonsense"), ("", None))

    def test_arrow_labels_can_send_several_packets_or_drop_one(self):
        from postcrew.render.scenes import edge_marks
        self.assertEqual(edge_marks("requests x4"), ("requests", 4, False))
        self.assertEqual(edge_marks("GET /a !"), ("GET /a", 1, True))
        self.assertEqual(edge_marks("plain"), ("plain", 1, False))

    def test_props_carry_states_counts_packets_and_the_closing_buttons(self):
        base = {"items": [], "nodes": [], "edges": [], "code": "", "language": "", "cells": [], "steps": []}
        scenes = [dict(base, layout="flow", on_screen="Down", narration="The load balancer sends requests to server three, which is down.",
                       nodes=["Load Balancer|lucide:network", "Server 3|lucide:server|down", "Server 1|lucide:server|3"],
                       edges=["Load Balancer > Server 3: GET /a x2 !", "Load Balancer > Server 1: ok"]),
                  dict(base, layout="statement", closing=True, on_screen="Like · Comment · Share · Subscribe",
                       narration="Please like, comment, share and subscribe.")]
        props, _ = rm.build_props(scenes, "long", None)
        nodes = props["scenes"][0]["nodes"]
        self.assertEqual((nodes[1]["state"], nodes[2]["count"]), ("down", 3))
        e = props["scenes"][0]["edges"][0]
        self.assertEqual((e["label"], e["n"], e["drop"]), ("GET /a", 2, True))
        buttons = props["scenes"][1]["buttons"]
        self.assertEqual([b["kind"] for b in buttons], ["like", "comment", "share", "subscribe"])
        self.assertTrue(all(b["svg"] and b["svg"]["body"] for b in buttons))
        self.assertEqual(len(props["scenes"][1]["cues"]), 4)

    def test_a_stat_scene_needs_a_number_and_only_remotion_draws_it(self):
        from postcrew.checks import script_problems
        spec = {"format": "long", "wps": 2.5, "target_seconds": 300, "max_words": 750, "renderer": "remotion"}
        sc = {"layout": "stat", "on_screen": "of traffic", "items": ["600 PB"], "narration": "Six hundred petabytes every day.", "part": "idea"}
        ok = [p for p in script_problems({"scenes": [sc], "text": sc["narration"]}, spec, {"label": "x"}, {"blocklist": [], "about": []}) if "'stat' scene" in p]
        self.assertEqual(ok, [])
        bad = dict(sc, items=["lots"])
        self.assertTrue(any("needs the number first" in p for p in script_problems({"scenes": [bad], "text": "x"}, spec, {"label": "x"}, {"blocklist": [], "about": []})))
        self.assertTrue(any("only by the Remotion" in p for p in script_problems({"scenes": [sc], "text": "x"}, dict(spec, renderer="ffmpeg"), {"label": "x"}, {"blocklist": [], "about": []})))
