"""The Video Editor: is the blackboard video in step with the voice, and are graphics fixed without making the voice again?"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from postcrew import voice
from postcrew.agents import credentials as cred_mod
from postcrew.agents.supervisor import crew_for
from postcrew.agents.video_review import VideoReviewAgent
from postcrew.crew import run_crew
from postcrew.render import audit, timeline
from postcrew.render import blackboard as bb
from postcrew.render import video as video_mod

import test_youtube_crew as yc
from helpers import ScriptedLLM, TempWorkspace, review, topic

NARR = ("A client sends a request. The load balancer receives it and picks a server. "
        "Server A or Server B handles it, and the response goes back to the client.")


def scene(**kw):
    d = {"layout": "diagram", "on_screen": "Load balancer", "narration": NARR, "items": [], "code": "", "language": "",
         "nodes": ["Client", "Load Balancer", "Server A", "Server B"], "seconds": 12,
         "edges": ["Client > Load Balancer: request", "Load Balancer > Server A: 50%", "Load Balancer > Server B: 50%",
                   "Server B > Client: response"]}
    d.update(kw)
    return d


def tone(path, secs):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={secs}", str(path)], check=True)


def entry(things, seconds=12.0, measured=False):
    return {"scene": 1, "start": 0, "seconds": seconds, "measured": measured, "drawn": [],
            "things": [{"cue": c, "what": w, "start": s, "end": s + 0.6} for c, w, s in things]}


class AuditTests(unittest.TestCase):
    def test_in_step_graphics_score_100(self):
        words = timeline.word_times(NARR, 12.0)
        things = [("Client", "box", timeline.cue_time("Client", words)),
                  ("Load Balancer", "box", timeline.cue_time("Load Balancer", words)),
                  ("Server A", "box", timeline.cue_time("Server A", words))]
        findings, score, _m = audit.check([scene()], [entry(things)])
        self.assertEqual((findings, score), ([], 100))

    def test_late_early_unspoken_and_dead_air_are_found(self):
        words = timeline.word_times(NARR, 12.0)
        said = timeline.cue_time("Server B", words)
        findings, score, _ = audit.check([scene()], [entry([("Client", "box", 0.0), ("Server B", "box", said + 3.0),   # 3 s late
                                                            ("Database", "box", 11.0)])])                               # never said
        kinds = {f["kind"] for f in findings}
        self.assertTrue({"late", "unspoken"} <= kinds, kinds)
        self.assertLess(score, 80)
        self.assertEqual(next(f for f in findings if f["kind"] == "unspoken")["severity"], "error")   # a box never named
        self.assertIn(f"drawn at {said + 3.0:.1f}s but the voice says it at {said:.1f}s", next(f for f in findings if f["kind"] == "late")["message"])
        idle, _s, _m = audit.check([scene()], [entry([("Client", "box", 0.5)], seconds=30.0)])   # then nothing for 29 seconds
        self.assertIn("dead_air", {f["kind"] for f in idle})

    def test_a_different_order_is_found_and_fixed_for_free(self):
        words = timeline.word_times(NARR, 12.0)
        wrong = scene(edges=["Server B > Client: response", "Client > Load Balancer: request",
                             "Load Balancer > Server A: 50%"])
        new = audit.reorder(wrong, words)
        self.assertEqual(new["edges"][0], "Client > Load Balancer: request")      # said first, so drawn first
        self.assertEqual(new["edges"][-1], "Server B > Client: response")
        self.assertIsNone(audit.reorder(new, words))                                # already in order
        self.assertEqual(new["narration"], NARR)                                    # the voice's words are untouched

    def test_points_follow_the_order_they_are_spoken(self):
        sc = {"layout": "points", "narration": "Use bcrypt for passwords. Add a unique salt to every one.",
              "items": ["Unique salt", "Use bcrypt"], "nodes": [], "edges": []}
        words = timeline.word_times(sc["narration"], 6.0)
        self.assertEqual(audit.reorder(sc, words)["items"], ["Use bcrypt", "Unique salt"])


@unittest.skipUnless(yc.HAVE_FFMPEG, "ffmpeg not installed")
class MeasuredOnTheVoiceTests(unittest.TestCase):
    def test_real_pauses_in_the_audio_correct_the_estimate(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1.0", "-f", "lavfi",
                            "-i", "anullsrc=r=44100:cl=mono:d=0.4", "-f", "lavfi", "-i", "sine=frequency=300:duration=2.5",
                            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=0.4", "-f", "lavfi", "-i",
                            "sine=frequency=300:duration=1.0", "-filter_complex", "[0][1][2][3][4]concat=n=5:v=0:a=1",
                            "-ar", "44100", str(d / "a.wav")], check=True)
            narr = "First part here. The second part is much longer than it looks on paper. Third part."
            est = timeline.word_times(narr, 5.65)
            words, measured = timeline.voice_words(narr, 5.65, d / "a.wav")
            self.assertTrue(measured)
            self.assertAlmostEqual(words[3][1], 1.4, delta=0.1)        # the second sentence really starts at 1.4 s
            self.assertGreater(abs(est[3][1] - 1.4), 0.15)             # the estimate alone was off
            self.assertFalse(timeline.voice_words(narr, 5.65, None)[1])

    def test_only_changed_scenes_are_drawn_again(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            clips = []
            for i in range(2):
                tone(d / f"s{i}.wav", 3.0)
                clips.append(d / f"s{i}.wav")
            scenes = [scene(narration="A client sends a request."), scene(narration="Then the server answers.")]
            bb.render(scenes, d / "o.mp4", "short", d / "w", audio=clips)
            first = (d / "w" / "seg-00.mp4").stat().st_mtime_ns
            second_before = (d / "w" / "seg-01.mp4").stat().st_mtime_ns
            scenes[1] = dict(scenes[1], on_screen="Answer")
            info = bb.render(scenes, d / "o.mp4", "short", d / "w", audio=clips, redo={1})
            self.assertEqual((d / "w" / "seg-00.mp4").stat().st_mtime_ns, first)           # kept
            self.assertGreater((d / "w" / "seg-01.mp4").stat().st_mtime_ns, second_before)  # drawn again
            self.assertEqual(len(info["timeline"]), 2)
            self.assertAlmostEqual(info["seconds"], 7.2, delta=0.3)   # the voice plus a calm 0.6 s after each scene


@unittest.skipUnless(yc.HAVE_FFMPEG, "ffmpeg not installed")
@mock.patch.object(cred_mod, "check_claude", return_value=yc.CLAUDE_OK)
@mock.patch.object(voice, "cached_synthesize", side_effect=yc.fake_tts)
class VideoEditorCrewTests(unittest.TestCase):
    def blackboard_ws(self, ws):
        yc.youtube_ws(ws)
        cfg = ws.config()
        cfg["platforms"]["youtube"]["video"]["renderer"] = "blackboard"
        ws.save_config(cfg)

    def script(self):
        s = yc.script()
        s["scenes"][1] = dict(s["scenes"][1], narration="The client asks the server. " + s["scenes"][1]["narration"], layout="diagram", nodes=["Client", "Server"], edges=["Client > Server: ask"],
                              on_screen="Ask")
        return yc.finish(s)

    def test_a_blackboard_video_gets_a_second_review_that_redraws_without_a_new_voice(self, tts, _claude):
        fix = {"verdict": "fix", "score": 92, "summary": "Labels now use the narrator's words.",
               "scenes": [{"scene": 2, "problem": "boxes are named differently from the narration", "layout": "diagram",
                           "on_screen": "Ask the server", "items": [], "code": "", "language": "",
                           "nodes": ["Client", "Server"], "edges": ["Client > Server: ask"], "cells": [], "steps": []}]}
        with TempWorkspace() as ws:
            self.blackboard_ws(ws)
            script = self.script()
            llm = ScriptedLLM({"topic": [topic("Default arguments", ())], "writer": [script], "editor": [review()],
                               "video_review": [fix, {"verdict": "pass", "score": 95, "summary": "ok", "scenes": []}]})
            res = run_crew(ws, yc.DAY, "short-tip", llm=llm, platform="youtube")
            self.assertTrue(res["ok"], res)
            steps = json.loads((ws.runs_dir / res["run_id"] / "status.json").read_text())["steps"]
            self.assertEqual(steps["video_review"]["state"], "passed")
            self.assertEqual(list(steps).index("video_review"), list(steps).index("media") + 1)
            self.assertEqual(tts.call_count, 5)                                  # the voice was made once per scene, never again
            out = json.loads((ws.runs_dir / res["run_id"] / "video_review.json").read_text())
            self.assertEqual((out["redrawn"], out["voice_regenerated"]), ([2], False))
            self.assertIn("video_review", llm.agents_called())
            post = ws.queue()[0]
            self.assertEqual(post["youtube"]["video_review"]["redrawn"], [2])
            self.assertEqual(video_mod.probe(ws.root / post["media"])["width"], 1080)
            self.assertEqual(post["youtube"]["scenes"][1]["on_screen"], "Ask the server")   # the queue shows what the video shows
            self.assertEqual(post["youtube"]["scenes"][1]["narration"], script["scenes"][1]["narration"])   # the words are the same

    def test_a_suggestion_that_breaks_a_rule_is_left_out(self, tts, _claude):
        bad = {"verdict": "fix", "score": 80, "summary": "x", "scenes": [{"scene": 2, "problem": "p", "layout": "diagram",
               "on_screen": "Ask", "items": [], "code": "", "language": "", "nodes": ["Client"], "edges": [], "cells": [], "steps": []}]}   # one box only
        with TempWorkspace() as ws:
            self.blackboard_ws(ws)
            llm = ScriptedLLM({"topic": [topic("Default arguments", ())], "writer": [self.script()], "editor": [review()],
                               "video_review": [bad]})
            res = run_crew(ws, yc.DAY, "short-tip", llm=llm, platform="youtube")
            self.assertTrue(res["ok"], res)
            out = json.loads((ws.runs_dir / res["run_id"] / "video_review.json").read_text())
            self.assertEqual(out["redrawn"], [])

    def test_slides_videos_are_not_reviewed_this_way(self, tts, _claude):
        with TempWorkspace() as ws:
            yc.youtube_ws(ws)   # the default renderer
            llm = ScriptedLLM({"topic": [topic("Default arguments", ())], "writer": [yc.script()], "editor": [review()]})
            res = run_crew(ws, yc.DAY, "short-tip", llm=llm, platform="youtube")
            self.assertTrue(res["ok"], res)
            steps = json.loads((ws.runs_dir / res["run_id"] / "status.json").read_text())["steps"]
            self.assertEqual(steps["video_review"]["state"], "skipped")
            self.assertNotIn("video_review", llm.agents_called())

    def test_crew_has_the_step_for_youtube_only(self, *_):
        self.assertIn("video_review", [a.id for a in crew_for("youtube")])
        self.assertNotIn("video_review", [a.id for a in crew_for("linkedin")])


if __name__ == "__main__":
    unittest.main()
