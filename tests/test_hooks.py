"""The Hooks agent and the quality checks behind it: sound, voice and frames, with no AI."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from postcrew.agents.hooks import HooksAgent  # noqa: E402
from postcrew.render import qa  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
SPANS = [(0.3, 3.7), (4.3, 7.7)]
SCENES = [(0, 4), (4, 8)]


def make(path, audio="sine=frequency=300:duration=8,volume=2.5", video_filter="", noaudio=False):
    """An 8-second 540x960 test video: a dark background with a picture in the middle, and a tone."""
    vf = "drawbox=x=100:y=300:w=340:h=300:color=white@1:t=fill,drawbox=x=140:y=640:w=260:h=80:color=0x7c3aed@1:t=fill" + (("," + video_filter) if video_filter else "")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x101018:s=540x960:d=8:r=10"]
    if not noaudio:
        cmd += ["-f", "lavfi", "-i", audio]
    cmd += ["-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p"] + ([] if noaudio else ["-c:a", "aac", "-shortest"]) + [str(path)]
    subprocess.run(cmd, check=True)


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class QaTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hooks-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def kinds(self, path, **kw):
        findings, score, _facts = qa.inspect(path, SPANS, SCENES, **kw)
        return {f["kind"]: f for f in findings}, score

    def test_a_good_video_has_no_faults(self):
        make(self.dir / "ok.mp4")
        kinds, score = self.kinds(self.dir / "ok.mp4")
        self.assertEqual([k for k, f in kinds.items() if f["severity"] == "error"], [])

    def test_no_audio_is_an_error(self):
        make(self.dir / "mute.mp4", noaudio=True)
        kinds, _ = self.kinds(self.dir / "mute.mp4")
        self.assertEqual(kinds["no_audio"]["severity"], "error")

    def test_a_silence_in_the_middle_of_the_narration_is_found(self):
        make(self.dir / "gap.mp4", audio="sine=frequency=300:duration=8,volume=2.5,volume=enable='between(t,1,5)':volume=0")
        kinds, score = self.kinds(self.dir / "gap.mp4")
        self.assertIn("silence", kinds)
        self.assertEqual(kinds["silence"]["scene"], 1)
        self.assertLess(score, 100)

    def test_a_scene_with_no_sound_is_found(self):
        make(self.dir / "quiet.mp4", audio="sine=frequency=300:duration=8,volume=2.5,volume=enable='between(t,4,8)':volume=0")
        kinds, _ = self.kinds(self.dir / "quiet.mp4")
        self.assertEqual(kinds["missing_sound"]["scene"], 2)

    def test_black_frames_and_an_empty_picture_are_found(self):
        make(self.dir / "black.mp4", video_filter="drawbox=x=0:y=0:w=iw:h=ih:color=black@1:t=fill:enable='between(t,1,2.5)'")
        kinds, _ = self.kinds(self.dir / "black.mp4")
        self.assertEqual(kinds["black"]["severity"], "error")
        self.assertEqual(kinds["black"]["scene"], 1)

    def test_something_drawn_at_the_edge_is_a_warning(self):
        make(self.dir / "edge.mp4", video_filter="drawbox=x=0:y=200:w=12:h=600:color=white@1:t=fill")
        kinds, _ = self.kinds(self.dir / "edge.mp4")
        self.assertEqual(kinds["edge"]["severity"], "warn")

    def test_loudness_and_clipping(self):
        make(self.dir / "quietmix.mp4", audio="sine=frequency=300:duration=8,volume=0.01")
        kinds, _ = self.kinds(self.dir / "quietmix.mp4")
        self.assertEqual(kinds["loudness"]["severity"], "error")


class FakeRun:
    def __init__(self):
        self.events = []

    def event(self, step, kind, message, level="info", **kw):
        self.events.append((kind, message))


def ctx_for(renderer, tmp):
    media = {"path": str(tmp / "v.mp4"), "renderer": renderer, "seconds": 8, "width": 540, "height": 960, "voice": "elevenlabs",
             "timeline": [{"start": 0, "seconds": 4}, {"start": 4, "seconds": 4}]}
    if renderer == "explainroo":
        media["explainroo"] = {"root": str(tmp), "rel": "videos/x"}
    return SimpleNamespace(outputs={"media": media, "writer": {"scenes": [{"narration": "a"}, {"narration": "b"}]}}, run=FakeRun(),
                           flags={}, dry_run=False, video={"format": "short"}, memory=None)


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class HooksAgentTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hooks-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_clean_video_passes_with_no_repair(self):
        make(self.dir / "v.mp4")
        out = HooksAgent().run(ctx_for("ffmpeg", self.dir), [])
        self.assertEqual((out["unresolved"], out["repaired"]), ([], False))

    def test_loudness_is_only_a_note_where_it_cannot_be_fixed(self):
        make(self.dir / "v.mp4", audio="sine=frequency=300:duration=8,volume=0.6")   # quiet, but a voice can be heard
        out = HooksAgent().run(ctx_for("ffmpeg", self.dir), [])
        self.assertEqual(out["unresolved"], [])
        self.assertTrue(any(f["kind"] == "loudness" and f["severity"] == "warn" for f in out["findings"]))

    def test_a_fault_it_cannot_fix_does_not_fail_the_run_but_holds_the_video(self):
        make(self.dir / "v.mp4", video_filter="drawbox=x=0:y=0:w=iw:h=ih:color=black@1:t=fill:enable='between(t,1,2.5)'")
        out = HooksAgent().run(ctx_for("ffmpeg", self.dir), [])
        self.assertTrue(out["unresolved"])
        self.assertIn("held for your approval", HooksAgent().summary(out))

    def test_an_explainroo_video_is_repaired_once_and_checked_again(self):
        make(self.dir / "v.mp4", audio="sine=frequency=300:duration=8,volume=2.5,volume=enable='between(t,1,5)':volume=0")
        ctx = ctx_for("explainroo", self.dir)
        good = self.dir / "good.mp4"
        make(good)

        def repair(self_, c, media, findings):
            shutil.copy(good, media["path"])
            return {"seconds": 8.0, "width": 540, "height": 960}
        with mock.patch("postcrew.agents.hooks.ExplainrooAgent.repair", repair):
            out = HooksAgent().run(ctx, [])
        self.assertTrue(out["repaired"])
        self.assertEqual(out["unresolved"], [])
        self.assertTrue(ctx.flags["hooks_repaired"])

    def test_a_retry_of_the_step_does_not_repair_again(self):
        make(self.dir / "v.mp4", audio="sine=frequency=300:duration=8,volume=2.5,volume=enable='between(t,1,5)':volume=0")
        ctx = ctx_for("explainroo", self.dir)
        ctx.flags["hooks_repaired"] = True
        with mock.patch("postcrew.agents.hooks.ExplainrooAgent.repair", side_effect=AssertionError("must not run")):
            out = HooksAgent().run(ctx, [])
        self.assertTrue(out["unresolved"])


if __name__ == "__main__":
    unittest.main()


class BlackFrameTests(unittest.TestCase):
    """The dark look is a near-black page: it is not a broken video. A frame that is really black still is."""

    def clip(self, colour, name):
        import subprocess
        import tempfile
        path = str(Path(tempfile.mkdtemp()) / name)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:s=320x240:d=2:r=10", "-pix_fmt", "yuv420p", path], check=True)
        return path

    def test_the_ink_page_is_not_black_but_black_is(self):
        from postcrew.render import qa
        self.assertEqual(qa.black_frames(self.clip("0x0D0D0D", "ink.mp4")), [])
        self.assertTrue(qa.black_frames(self.clip("0x000000", "black.mp4")))
        self.assertEqual(qa.black_frames(self.clip("0xF5F2EB", "paper.mp4")), [])
