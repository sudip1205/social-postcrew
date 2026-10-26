import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from postcrew import platforms, voice
from postcrew.agents import credentials as cred_mod
from postcrew.agents.blackboard import BlackboardAgent
from postcrew.agents.supervisor import crew_for
from postcrew.agents.video import VideoAgent
from postcrew.crew import run_crew
from postcrew.render import blackboard as bb
from postcrew.render import timeline
from postcrew.render import video as video_mod
from postcrew.workspace import validate_config

import test_youtube_crew as yc
from helpers import ScriptedLLM, TempWorkspace

FFMPEG = shutil.which("ffmpeg") is not None
NARRATION = ("A client sends a request. The load balancer receives it and picks a server. "
             "Server A or Server B handles it, and the response goes back to the client.")
DIAGRAM = {"layout": "diagram", "on_screen": "Load balancer", "narration": NARRATION, "items": [], "code": "", "language": "",
           "nodes": ["Client", "Load Balancer", "Server A", "Server B"],
           "edges": ["Client > Load Balancer: request", "Load Balancer > Server A: 50%", "Load Balancer > Server B: 50%",
                     "Server B > Client: response"]}
POINTS = {"layout": "points", "on_screen": "Why salt", "narration": "Salt makes every hash different. Use bcrypt.",
          "items": ["Unique salt", "Use bcrypt"], "code": "", "language": "", "nodes": [], "edges": []}
CODE = {"layout": "code", "on_screen": "Two Sum", "narration": "Store each number in a map.", "language": "python",
        "code": "seen = {}\nfor i, n in enumerate(nums):\n    seen[n] = i", "items": [], "nodes": [], "edges": []}
TITLE = {"layout": "title", "on_screen": "Circuit breaker", "narration": "Fail fast.", "items": ["Closed, open, half-open"],
         "code": "", "language": "", "nodes": [], "edges": []}


def tone(path, secs):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}", str(path)],
                   check=True)


class TimelineTests(unittest.TestCase):
    def test_word_times_cover_the_scene_and_pause_at_full_stops(self):
        w = timeline.word_times("One two. Three four", 10.0)
        self.assertAlmostEqual(w[-1][2], 10.0 - 0.35, places=3)
        self.assertGreater(w[2][1] - w[1][2] + 1e-9, -1e-6)
        self.assertGreater(w[1][2] - w[1][1], w[0][2] - w[0][1] - 1e-9)   # "two." carries the pause

    def test_cue_finds_the_word_in_any_form(self):
        w = timeline.word_times(NARRATION, 12.0)
        self.assertLess(timeline.cue_time("Client", w), timeline.cue_time("Load Balancer", w))
        self.assertLess(timeline.cue_time("Load Balancer", w), timeline.cue_time("Server B", w))
        self.assertIsNone(timeline.cue_time("Database", w))

    def test_schedule_is_ordered_one_at_a_time_and_ends_before_the_scene_does(self):
        items = [{"cue": None, "dur": 0.6}, {"cue": "client", "dur": 0.7}, {"cue": "balancer", "dur": 0.7},
                 {"cue": None, "dur": 0.5}, {"cue": "response", "dur": 0.6}]
        slots = timeline.schedule(items, timeline.word_times(NARRATION, 12.0), 12.0)
        for (s1, e1), (s2, e2) in zip(slots, slots[1:]):
            self.assertLessEqual(e1, s2 + 1e-6)
        self.assertLessEqual(slots[-1][1], 12.0 - 0.35 + 1e-6)

    def test_a_cue_is_drawn_when_the_voice_says_it(self):
        w = timeline.word_times(NARRATION, 12.0)
        slots = timeline.schedule([{"cue": None, "dur": 0.5}, {"cue": "response", "dur": 0.5}], w, 12.0)
        self.assertAlmostEqual(slots[1][0], timeline.cue_time("response", w) - timeline.LEAD, places=2)

    def test_too_late_cues_are_squeezed_in(self):
        slots = timeline.schedule([{"cue": None, "dur": 1.0}] + [{"cue": "client", "dur": 1.0}] * 5,
                                  timeline.word_times("a b c client", 3.0), 3.0)
        self.assertLessEqual(slots[-1][1], 3.0 - 0.35 + 1e-6)


class BoardTests(unittest.TestCase):
    def test_every_layout_has_things_to_draw_and_renders_in_both_formats(self):
        for scene in (DIAGRAM, POINTS, CODE, TITLE):
            self.assertGreaterEqual(len(bb.build(scene, "short")), 2, scene["layout"])
            for fmt, size in video_mod.FORMATS.items():
                self.assertEqual(bb.still(scene, fmt, "KICKER", "example.com", "a caption").size, size)

    def test_a_diagram_draws_each_box_once_then_arrows_in_order(self):
        items = bb.build(DIAGRAM, "long")
        self.assertEqual(sum(isinstance(i, bb.Strokes) for i in items), 1 + 4 + 4)   # underline, boxes, arrows
        cues = [i.cue for i in items if i.cue]
        self.assertLess(cues.index("Client"), cues.index("request"))
        self.assertLess(cues.index("request"), cues.index("Server A"))

    def test_the_picture_builds_up_over_time(self):
        g = bb._geom("short")
        before, after = bb.still(DIAGRAM, "short"), bb.still(dict(DIAGRAM, edges=[]), "short")
        self.assertNotEqual(before.tobytes(), after.tobytes())

    def test_scene_frames_follow_the_voice_and_repeat_frames_are_written_once(self):
        with tempfile.TemporaryDirectory() as d:
            frames, slots = bb.render_scene(DIAGRAM, "short", 6.0, d, 0, 1, "SYSTEM DESIGN", "example.com")
            self.assertAlmostEqual(sum(s for _p, s in frames), 6.0, places=1)
            self.assertLess(len(frames), 6.0 * bb.DRAW_FPS)            # still moments are one frame
            self.assertEqual(len(slots), len(bb.build(DIAGRAM, "short")))
            self.assertLess(slots[-1][1], 6.0)


@unittest.skipUnless(FFMPEG, "ffmpeg is not installed")
class RenderTests(unittest.TestCase):
    def test_video_is_as_long_as_the_voice_clips(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            clips = []
            for i, secs in enumerate((3.0, 2.0)):
                tone(d / f"s{i}.wav", secs)
                clips.append(d / f"s{i}.wav")
            info = bb.render([DIAGRAM, POINTS], d / "out.mp4", "short", d / "w", audio=clips, kicker="K", handle="h")
            self.assertEqual((info["width"], info["height"]), (1080, 1920))
            self.assertAlmostEqual(info["seconds"], 5.0 + 2 * video_mod.TAIL_S, delta=0.3)
            self.assertTrue(video_mod.probe(d / "out.mp4")["has_audio"])
            self.assertEqual([t["scene"] for t in info["timeline"]], [1, 2])
            self.assertAlmostEqual(info["timeline"][1]["start"], info["timeline"][0]["seconds"], places=1)

    def test_without_a_voice_the_word_count_sets_the_pace(self):
        with tempfile.TemporaryDirectory() as d:
            info = bb.render([TITLE], Path(d) / "o.mp4", "long", Path(d) / "w")
            self.assertEqual((info["width"], info["height"]), (1920, 1080))


class WiringTests(unittest.TestCase):
    def test_the_crew_gets_the_blackboard_producer_only_when_asked(self):
        with TempWorkspace() as ws:
            cfg = platforms.view(ws.config(), "youtube")
            ids = lambda crew: [type(a) for a in crew if a.id == "media"]
            self.assertEqual(ids(crew_for("youtube", cfg, "short-tip")), [VideoAgent])
            self.assertEqual(ids(crew_for("youtube", dict(cfg, video=dict(cfg["video"], renderer="blackboard")), "short-tip")),
                             [BlackboardAgent])
            cats = {**cfg["categories"], "short-tip": dict(cfg["categories"]["short-tip"], renderer="blackboard")}
            self.assertEqual(ids(crew_for("youtube", dict(cfg, categories=cats), "short-tip")), [BlackboardAgent])
            self.assertEqual(ids(crew_for("youtube", dict(cfg, categories=cats), "explainer")), [VideoAgent])

    def test_config_accepts_the_blackboard_renderer_and_rejects_others(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            yt = cfg["platforms"]["youtube"]
            yt["enabled"] = True
            yt["video"]["renderer"] = "blackboard"
            self.assertEqual(validate_config(cfg), [])
            yt["video"]["renderer"] = "chalk"
            self.assertTrue(any("renderer" in e for e in validate_config(cfg)))
            yt["video"]["renderer"] = "ffmpeg"
            yt["categories"]["short-tip"]["renderer"] = "mcp"
            self.assertTrue(any("short-tip.renderer" in e for e in validate_config(cfg)))


@unittest.skipUnless(FFMPEG, "ffmpeg is not installed")
@mock.patch.object(cred_mod, "check_claude", return_value=yc.CLAUDE_OK)
@mock.patch.object(voice, "cached_synthesize", side_effect=yc.fake_tts)
class BlackboardCrewTests(unittest.TestCase):
    def test_the_voice_is_made_first_and_the_board_is_drawn_to_it(self, tts, _claude):
        seen = {}
        real = bb.render

        def spy(*a, **kw):
            seen["tts_calls"], seen["audio"] = tts.call_count, kw.get("audio")
            return real(*a, **kw)

        with TempWorkspace() as ws, mock.patch.object(bb, "render", spy):
            yc.youtube_ws(ws)
            cfg = ws.config()
            cfg["platforms"]["youtube"]["video"]["renderer"] = "blackboard"
            ws.save_config(cfg)
            llm = ScriptedLLM({"topic": [yc.topic("Default arguments", ())], "writer": [yc.script()], "editor": [yc.review()]})
            res = run_crew(ws, yc.DAY, "short-tip", llm=llm, platform="youtube")
            self.assertTrue(res["ok"], res)
            self.assertEqual(seen["tts_calls"], 5)                    # every scene was voiced before the first stroke
            self.assertEqual(len(seen["audio"]), 5)
            post = ws.queue()[0]
            self.assertEqual(video_mod.probe(ws.root / post["media"])["width"], 1080)
            run = json.loads((ws.runs_dir / res["run_id"] / "status.json").read_text())
            self.assertEqual(run["steps"]["media"]["state"], "passed")


if __name__ == "__main__":
    unittest.main()
