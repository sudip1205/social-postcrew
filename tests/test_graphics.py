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
