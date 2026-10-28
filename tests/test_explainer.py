"""The explainer renderer: a growing picture, drawn slowly to the voice."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from postcrew import platforms, voice
from postcrew.agents import credentials as cred_mod
from postcrew.agents.blackboard import ExplainerAgent
from postcrew.agents.supervisor import crew_for
from postcrew.checks import script_problems
from postcrew.crew import run_crew
from postcrew.render import explainer as ex
from postcrew.render import timeline
from postcrew.render import video as video_mod
from postcrew.render.scenes import ICONS, parse_edge, split_node
from postcrew.workspace import validate_config

import test_youtube_crew as yc
from helpers import ScriptedLLM, TempWorkspace, review, topic


def diagram(nodes, edges, narration, title="A chapter"):
    return {"layout": "diagram", "on_screen": title, "narration": narration, "items": [], "code": "", "language": "",
            "nodes": nodes, "edges": edges, "seconds": 10}


S1 = diagram(["Client|client", "Load Balancer|gateway", "Server A|server"],
             ["Client > Load Balancer: request", "Load Balancer > Server A: pick"],
             "A client sends a request. The load balancer receives it and picks a server.", "How a request flows")
S2 = diagram(["Server A|server", "Database|database", "Cache|cache"],
             ["Server A > Cache: read", "Cache > Database: miss"],
             "Server A reads from a cache. On a miss the cache asks the database.", "Where the data lives")
OTHER = diagram(["Phone|phone", "Auth Server|lock"], ["Phone > Auth Server: login"], "A phone logs in.", "Login")
TITLE = {"layout": "title", "on_screen": "How load balancing works", "narration": "Here is how it works.", "items": ["in 60 seconds"],
         "nodes": [], "edges": [], "code": "", "language": ""}
POINTS = {"layout": "points", "on_screen": "Three ways", "narration": "Round robin takes turns. Least connections picks the quietest.",
          "items": ["Round robin", "Least connections"], "nodes": [], "edges": [], "code": "", "language": ""}
CODE = {"layout": "code", "on_screen": "Round robin", "narration": "Keep an index and move it along.", "language": "python",
        "code": "i = 0\ndef pick(s):\n    global i\n    i += 1\n    return s[i % len(s)]", "items": [], "nodes": [], "edges": []}


def tone(path, secs):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={secs}", str(path)], check=True)


class IconAndNodeTests(unittest.TestCase):
    def test_every_icon_draws_and_names_are_understood(self):
        for kind in ICONS:
            self.assertEqual(ex.icon2x(kind, 40, ex.TEAL).size, (80, 80), kind)
        self.assertEqual(split_node("API Gateway|gateway"), ("API Gateway", "gateway"))
        self.assertEqual(parse_edge("Client > API Gateway: call", ["Client|client", "API Gateway|gateway"]), (0, 1, "call"))
        self.assertEqual(ex.guess_icon("Redis Cache"), "cache")
        self.assertEqual(ex.guess_icon("Postgres"), "database")
        self.assertEqual(ex.guess_icon("Thing", "lock"), "lock")

    def test_icons_are_checked_in_scripts(self):
        spec = {"format": "short", "target_seconds": 45, "max_words": 112}
        s = yc.script()
        s["scenes"][1] = dict(s["scenes"][1], layout="diagram", nodes=["Client|client", "Server|banana"], edges=["Client > Server: x"],
                              on_screen="Ask")
        problems = script_problems(yc.finish(s), spec, {"label": "x"}, {"blocklist": [], "about": []})
        self.assertTrue(any("icon after |" in p for p in problems), problems)
        s["scenes"][1]["nodes"] = ["Client|client", "Server|server"]
        problems = script_problems(yc.finish(s), spec, {"label": "x"}, {"blocklist": [], "about": []})
        self.assertFalse(any("icon" in p or "diagram" in p for p in problems), problems)


class CanvasTests(unittest.TestCase):
    def test_consecutive_diagrams_that_share_a_box_are_one_canvas(self):
        groups = ex.plan_groups([TITLE, S1, S2, POINTS, OTHER])
        self.assertIsNone(groups[0])
        self.assertEqual(groups[1]["carry_nodes"], [])
        self.assertEqual([n.split("|")[0] for n in groups[2]["nodes"]],
                         ["Client", "Load Balancer", "Server A", "Database", "Cache"])      # the union, laid out once
        self.assertEqual(sorted(groups[2]["carry_nodes"]), ["client", "load balancer", "server a"])   # what scene 1 drew
        self.assertIsNone(groups[3])
        self.assertEqual(groups[4]["carry_nodes"], [])            # nothing shared: a new canvas

    def test_what_an_earlier_scene_drew_is_already_there(self):
        groups = ex.plan_groups([S1, S2])
        items = ex.build(S2, "short", groups[1])
        pre = [i for i in items if i.pre]
        self.assertTrue({"Client", "Load Balancer"} <= {i.cue for i in pre if i.what == "box"})
        self.assertTrue(all(not i.pre for i in ex.timed(items)))
        new = {i.cue for i in ex.timed(items) if i.what == "box"}
        self.assertEqual(new, {"Cache", "Database"})              # only the new boxes animate in
        first = {i.cue: i.xy for i in ex.build(S1, "short", groups[0]) if i.what == "box"}
        again = {i.cue: i.xy for i in items if i.what == "box"}
        self.assertEqual(first["Client"], again["Client"])         # and nothing moves between scenes

    def test_every_layout_renders_in_both_formats(self):
        for scene in (TITLE, S1, POINTS, CODE):
            for fmt, size in video_mod.FORMATS.items():
                self.assertEqual(ex.still(scene, fmt, "KICKER", "example.com", at=6.0).size, size, (scene["layout"], fmt))


class CaptionTests(unittest.TestCase):
    def test_captions_are_short_chunks_timed_to_the_voice(self):
        words = timeline.word_times("A client sends a request. The load balancer receives it, and picks a server.", 9.0)
        chunks = ex.caption_chunks(words, 9.0)
        self.assertTrue(all(1 <= len(c[0].split()) <= 5 for c in chunks), chunks)
        self.assertTrue(chunks[0][0].startswith("A client"))
        self.assertEqual(chunks[0][1], 0.0)
        starts = [c[1] for c in chunks]
        self.assertEqual(starts, sorted(starts))
        self.assertAlmostEqual(chunks[-1][2], 9.0)
        self.assertTrue(any(c[0].endswith(("request.", "it,")) for c in chunks))     # cut at the punctuation

    def test_a_scene_is_drawn_to_its_length_and_still_moments_are_one_frame(self):
        with tempfile.TemporaryDirectory() as d:
            frames, slots = ex.render_scene(S1, "short", 12.0, d, 0, 1, "KICK", "example.com")
            self.assertAlmostEqual(sum(s for _p, s in frames), 12.0, places=1)
            self.assertLess(len(frames), 12.0 * ex.DRAW_FPS)
            self.assertEqual(len(slots), len(ex.timed(ex.build(S1, "short"))))
            self.assertLess(slots[-1][1], 12.0)
            self.assertGreaterEqual(slots[1][0] - slots[0][0], 0.39)           # things may overlap, but never start together


@unittest.skipUnless(yc.HAVE_FFMPEG, "ffmpeg not installed")
class RenderTests(unittest.TestCase):
    def test_a_video_is_as_long_as_the_voice_and_only_changed_scenes_are_redrawn(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            clips = []
            for i in range(2):
                tone(d / f"s{i}.wav", 4.0)
                clips.append(d / f"s{i}.wav")
            info = ex.render([S1, S2], d / "o.mp4", "short", d / "w", audio=clips, kicker="K", handle="h")
            self.assertEqual((info["width"], info["height"]), (1080, 1920))
            self.assertAlmostEqual(info["seconds"], 8.7, delta=0.4)
            self.assertTrue(video_mod.probe(d / "o.mp4")["has_audio"])
            before = (d / "w" / "seg-00.mp4").stat().st_mtime_ns
            info = ex.render([S1, dict(S2, on_screen="Changed")], d / "o.mp4", "short", d / "w", audio=clips, redo={1})
            self.assertEqual((d / "w" / "seg-00.mp4").stat().st_mtime_ns, before)       # scene 1 kept
            self.assertEqual(len(info["timeline"]), 2)
            self.assertTrue(all("what" in t for t in info["timeline"][0]["things"]))


class SettingsTests(unittest.TestCase):
    def test_slow_pace_means_fewer_words_and_longer_pauses(self):
        slow = platforms.video_spec({"video": {"format": "short", "target_seconds": 90, "pace": "slow"}})
        normal = platforms.video_spec({"video": {"format": "short", "target_seconds": 90, "pace": "normal"}})
        self.assertEqual((slow["max_words"], normal["max_words"]), (180, 225))
        self.assertEqual(slow["wps"], 2.0)
        text = "One thing. Another thing."
        self.assertIn('<break time="0.6s" />', voice.prepare(text, pace="slow"))
        self.assertIn('<break time="0.35s" />', voice.prepare(text, pace="normal"))

    def test_shorts_may_run_three_minutes(self):
        self.assertEqual(platforms.video_spec({"video": {"format": "short", "target_seconds": 170}})["target_seconds"], 170)
        self.assertEqual(platforms.video_spec({"video": {"format": "short", "target_seconds": 500}})["target_seconds"], 180)
        with TempWorkspace() as ws:
            cfg = ws.config()
            yt = cfg["platforms"]["youtube"]
            yt["enabled"] = True
            yt["video"].update(format="short", target_seconds=150)
            self.assertEqual(validate_config(cfg), [])
            yt["video"]["target_seconds"] = 200
            self.assertTrue(any("target_seconds" in e for e in validate_config(cfg)))
            yt["video"].update(target_seconds=90, pace="fast")
            self.assertTrue(any("video.pace" in e for e in validate_config(cfg)))

    def test_explainer_is_a_renderer_and_the_default(self):
        from postcrew.defaults import DEFAULT_CONFIG
        self.assertEqual(DEFAULT_CONFIG["platforms"]["youtube"]["video"]["renderer"], "explainer")
        self.assertEqual(DEFAULT_CONFIG["platforms"]["youtube"]["video"]["pace"], "slow")
        with TempWorkspace() as ws:
            cfg = platforms.view(ws.config(), "youtube")
            ids = lambda crew: [type(a) for a in crew if a.id == "media"]
            self.assertEqual(ids(crew_for("youtube", dict(cfg, video=dict(cfg["video"], renderer="explainer")), "short-tip")),
                             [ExplainerAgent])


@unittest.skipUnless(yc.HAVE_FFMPEG, "ffmpeg not installed")
@mock.patch.object(cred_mod, "check_claude", return_value=yc.CLAUDE_OK)
@mock.patch.object(voice, "cached_synthesize", side_effect=yc.fake_tts)
class ExplainerCrewTests(unittest.TestCase):
    def test_the_crew_makes_an_explainer_video_and_the_video_editor_checks_it(self, tts, _claude):
        with TempWorkspace() as ws:
            yc.youtube_ws(ws)
            cfg = ws.config()
            cfg["platforms"]["youtube"]["video"]["renderer"] = "explainer"
            ws.save_config(cfg)
            script = yc.script()
            script["scenes"][1] = dict(script["scenes"][1], layout="diagram", on_screen="Ask the server",
                                       nodes=["Client|client", "Server|server"], edges=["Client > Server: ask"])
            llm = ScriptedLLM({"topic": [topic("Default arguments", ())], "writer": [yc.finish(script)], "editor": [review()],
                               "video_review": [{"verdict": "pass", "score": 95, "summary": "in step", "scenes": []}]})
            res = run_crew(ws, yc.DAY, "short-tip", llm=llm, platform="youtube")
            self.assertTrue(res["ok"], res)
            run = ws.runs_dir / res["run_id"]
            media = json.loads((run / "media.json").read_text())
            self.assertEqual(media["renderer"], "explainer")
            steps = json.loads((run / "status.json").read_text())["steps"]
            self.assertEqual(steps["video_review"]["state"], "passed")      # the second review ran on the explainer too
            self.assertEqual(tts.call_count, 5)
            self.assertEqual(video_mod.probe(ws.root / ws.queue()[0]["media"])["width"], 1080)


if __name__ == "__main__":
    unittest.main()


class TraceAndFlowTests(unittest.TestCase):
    TRACE = {"layout": "trace", "on_screen": "Two Sum", "cells": ["2", "7", "11", "15"], "items": [], "nodes": [], "edges": [],
             "narration": "Left starts at the first number and right at the last. Two plus fifteen is seventeen, too big, so right moves left. "
                          "Two plus seven is nine. Found it.",
             "steps": [{"say": "Left starts", "pointers": ["L=0", "R=3"], "active": [0, 3], "found": [], "out": [], "note": "2 + 15 = 17", "memo": []},
                       {"say": "right moves left", "pointers": ["L=0", "R=2"], "active": [0, 2], "found": [], "out": [3], "note": "2 + 11 = 13", "memo": []},
                       {"say": "Two plus seven", "pointers": ["L=0", "R=1"], "active": [], "found": [0, 1], "out": [2, 3], "note": "2 + 7 = 9", "memo": ["target = 9"]}]}

    def test_trace_problems_are_found(self):
        from postcrew.render.scenes import trace_problem
        self.assertEqual(trace_problem(self.TRACE), "")
        bad = dict(self.TRACE, steps=[dict(self.TRACE["steps"][0], pointers=["L=9"]), self.TRACE["steps"][1]])
        self.assertIn("pointer", trace_problem(bad))
        self.assertIn("cells", trace_problem(dict(self.TRACE, cells=["1"])))

    def test_trace_steps_are_timed_to_the_voice_and_pointers_move(self):
        import tempfile
        from postcrew.render import explainer as ex
        with tempfile.TemporaryDirectory() as d:
            frames, slots = ex.render_scene(self.TRACE, "long", 14.0, d, 0, 1, fps=4)
        items = ex.timed(ex.build(self.TRACE, "long"))
        starts = [s for it, (s, _e) in zip(items, slots) if it.what == "step"]
        self.assertEqual(len(starts), 3)
        self.assertEqual(starts, sorted(starts))
        self.assertGreater(starts[2] - starts[0], 2.0)   # spread over the narration, not all at once
        self.assertGreater(len({str(p) for p, _d in frames}), 10)

    def test_flow_scene_draws_every_hop(self):
        from postcrew.render import explainer as ex
        sc = {"layout": "flow", "on_screen": "One request", "items": [], "cells": [], "steps": [],
              "narration": "The client sends get cart to the load balancer. The load balancer forwards it to the server. The server answers.",
              "nodes": ["Client", "Load Balancer", "Server"],
              "edges": ["Client > Load Balancer: GET /cart", "Load Balancer > Server: forward", "Server > Client: 3 items"]}
        items = ex.build(sc, "short")
        self.assertEqual([it.kind for it in items].count("step"), 3)
        self.assertEqual(ex.still(sc, "short", at=11).size, (1080, 1920))

    def test_checks_accept_trace_and_flow(self):
        from postcrew.checks import SCENE_LAYOUTS
        self.assertIn("trace", SCENE_LAYOUTS)
        self.assertIn("flow", SCENE_LAYOUTS)


class StrayLetterTests(unittest.TestCase):
    def test_lone_lowercase_letters_are_sent_back_to_the_writer(self):
        from postcrew import platforms
        from postcrew.checks import script_problems
        spec = platforms.video_spec({"video": {"format": "short", "pace": "normal"}, "categories": {}}, {})
        sc = [{"layout": "statement", "narration": "Right moves over a, b, c. It is a window.", "on_screen": "x", "items": [], "nodes": [],
               "edges": [], "cells": [], "steps": []}] * 4
        out = script_problems({"scenes": sc, "text": " ".join(s["narration"] for s in sc), "title": "t" * 20, "description": "d" * 50,
                               "tags": ["a", "b", "c"], "thumbnail_text": "ab"}, spec, {}, {})
        self.assertTrue(any("lone lowercase letter" in p for p in out), out)
