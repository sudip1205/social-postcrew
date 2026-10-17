"""Renderers: posters fit their 1080x1350 canvas, and the Java shown in each animation really runs."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from postcrew.render import tracers
from postcrew.render.animate import render_animation, render_poster_video
from postcrew.render.poster import PosterError, poster_stages, render_poster


class PosterTests(unittest.TestCase):
    def test_layouts_render_to_spec(self):
        from PIL import Image
        specs = [
            {"layout": "points", "kicker": "AI news", "title": "A [[title]]", "items": [{"head": "a", "body": "b"}] * 3},
            {"layout": "steps", "kicker": "Build", "title": "T", "items": [{"head": "a"}, {"head": "b"}, {"head": "c"}],
             "result": "done"},
            {"layout": "code", "kicker": "Tip", "title": "T", "language": "python", "code": "x = 1\nprint(x)",
             "caption": "c"},
            {"layout": "flow", "kicker": "Sec", "title": "T", "items": [{"label": "a", "via": "v"}, {"label": "b"}]},
        ]
        with tempfile.TemporaryDirectory() as d:
            for s in specs:
                out = render_poster(s, Path(d) / f"{s['layout']}.png")
                with Image.open(out) as im:
                    self.assertEqual(im.size, (1080, 1350))

    def test_stages_build_up_to_the_finished_poster(self):
        from PIL import ImageChops
        spec = {"layout": "steps", "kicker": "Build", "title": "T", "result": "done",
                "items": [{"head": "a"}, {"head": "b"}, {"head": "c"}]}
        stages = poster_stages(spec)
        self.assertEqual(len(stages), 4)                     # the header, then one step at a time
        with tempfile.TemporaryDirectory() as d:
            render_poster(spec, Path(d) / "p.png")
            from PIL import Image
            with Image.open(Path(d) / "p.png") as full:
                self.assertIsNone(ImageChops.difference(stages[-1], full.convert("RGB")).getbbox())
        self.assertIsNotNone(ImageChops.difference(stages[0], stages[1]).getbbox())
        code = {"layout": "code", "kicker": "Tip", "title": "T", "language": "python",
                "code": "\n".join(f"x{i} = {i}" for i in range(12))}
        self.assertLessEqual(len(poster_stages(code)), 8)  # long code is revealed a few lines at a time

    def test_overflow_is_reported_not_clipped(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(PosterError):
            render_poster({"layout": "points", "kicker": "k", "title": "t",
                           "items": [{"head": "h" * 40, "body": "long " * 120}] * 5}, Path(d) / "x.png")

    def test_wide_code_line_rejected(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(PosterError):
            render_poster({"layout": "code", "kicker": "k", "title": "t", "language": "python",
                           "code": "x = " + "1" * 120 + "\ny = 2"}, Path(d) / "x.png")


class TracerTests(unittest.TestCase):
    def test_every_trace_ends_correctly_and_highlights_real_lines(self):
        for t in tracers.TRACERS.values():
            frames, result = t.run()
            n = len(t.java.split("\n"))
            self.assertTrue(all(f["line"] is None or 1 <= f["line"] <= n for f in frames), t.id)
            self.assertGreater(sum(f["dur"] for f in frames), 15, t.id)

    @unittest.skipUnless(shutil.which("java"), "java not installed")
    def test_java_on_screen_matches_trace(self):
        for t in tracers.TRACERS.values():
            _, expected = t.run()
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "Main.java").write_text(tracers.java_program(t))
                r = subprocess.run(["java", "Main.java"], cwd=d, capture_output=True, text=True, timeout=120)
                self.assertEqual(r.stdout.strip(), expected, f"{t.id}: {r.stderr[-300:]}")

    def test_java_lines_fit_the_code_panel(self):
        from postcrew.render.animate import check_code_fits
        for t in tracers.TRACERS.values():
            check_code_fits(t.java.split("\n"))  # raises if a line would be clipped on screen

    def test_next_algo_skips_used(self):
        self.assertEqual(tracers.next_algo([]).id, "mergesort")
        self.assertEqual(tracers.next_algo(["Merge Sort in Java"]).id, "binarysearch")
        self.assertIn("quicksort", tracers.used_algos(["Quick Sort in 14 lines"]))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_animation_renders_h264_1080x1350(self):
        with tempfile.TemporaryDirectory() as d:
            info = render_animation("binarysearch", Path(d) / "a.mp4")
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height",
                                    "-of", "csv=p=0", str(Path(d) / "a.mp4")], capture_output=True, text=True)
            self.assertIn("h264,1080,1350", probe.stdout)
            self.assertTrue(15 <= info["seconds"] <= 60)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_animated_poster_renders_h264_1080x1350(self):
        spec = {"layout": "points", "kicker": "AI news", "title": "A [[title]]", "items": [{"head": "a", "body": "b"}] * 4}
        with tempfile.TemporaryDirectory() as d:
            info = render_poster_video(spec, Path(d) / "p.mp4")
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height",
                                    "-of", "csv=p=0", str(Path(d) / "p.mp4")], capture_output=True, text=True)
            self.assertIn("h264,1080,1350", probe.stdout)
            self.assertTrue(15 <= info["seconds"] <= 60, info)


if __name__ == "__main__":
    unittest.main()
