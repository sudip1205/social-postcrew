import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from postcrew.render import mcp_renderer
from postcrew.render.mcp_renderer import McpClient, McpError, render_clips
from postcrew.render.scenes import FORMATS, draw_frame, split_captions
from postcrew.render.video import check_video, compose, probe

FFMPEG = shutil.which("ffmpeg") is not None
LONG = "This is a very long sentence about nothing in particular that keeps going " * 12
CODE = "\n".join(f"def function_{i}(argument_one, argument_two): return argument_one + argument_two * {i}" * 2
                 for i in range(30))
SCENES = [
    {"layout": "title", "narration": "Welcome to the show. Today we talk about queues.", "on_screen": "Queues",
     "items": ["A short tour"], "code": "", "language": "", "seconds": 1.0},
    {"layout": "points", "narration": "Three things matter here, first speed, then safety.", "on_screen": "Why",
     "items": ["Fast", "Safe", "Simple"], "code": "", "language": "", "seconds": 1.0},
]


def tone(path, secs):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}",
                    str(path)], check=True)


class CaptionTests(unittest.TestCase):
    def test_properties(self):
        text = "First, a sentence. Second one is here, with a clause, and more words to push past the limit. Done!"
        for mw in (3, 5, 9):
            chunks = split_captions(text, mw)
            self.assertTrue(all(c.strip() for c in chunks))
            self.assertTrue(all(len(c.split()) <= mw for c in chunks))
            self.assertEqual(" ".join(chunks).split(), text.split())

    def test_empty(self):
        self.assertEqual(split_captions(""), [])
        self.assertEqual(split_captions("   "), [])


class FrameTests(unittest.TestCase):
    def test_sizes(self):
        for fmt, size in FORMATS.items():
            for layout in ("title", "statement", "points", "code", "bogus"):
                sc = {"layout": layout, "on_screen": LONG, "items": [LONG] * 7, "code": CODE, "language": "python"}
                im = draw_frame(sc, fmt, LONG, "kicker " * 20, "@handle" * 10, 2, 5)
                self.assertEqual(im.size, size)
                im = draw_frame({"layout": layout}, fmt)
                self.assertEqual(im.size, size)
                self.assertEqual(draw_frame({}, fmt, "", "", "", 0, 0).size, size)


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_silent_and_checks(self):
        calls = []
        out = self.tmp / "a.mp4"
        r = compose(SCENES, out, "short", self.tmp / "w", handle="@me", kicker="Demo",
                    progress=lambda d, t: calls.append((d, t)))
        info = probe(out)
        self.assertEqual((info["width"], info["height"]), (1080, 1920))
        self.assertTrue(info["has_audio"])
        self.assertAlmostEqual(info["seconds"], 2.0, delta=0.5)
        self.assertAlmostEqual(r["seconds"], info["seconds"], delta=0.1)
        self.assertEqual(calls, [(1, 2), (2, 2)])
        checks = check_video(out, "short")
        self.assertTrue(all(c["ok"] for c in checks), checks)
        bad = {c["label"]: c["ok"] for c in check_video(out, "long")}
        self.assertFalse(bad["Aspect ratio"])

    def test_per_scene_audio_long(self):
        files = []
        for i, s in enumerate((1.0, 1.5)):
            f = self.tmp / f"s{i}.wav"
            tone(f, s)
            files.append(f)
        out = self.tmp / "b.mp4"
        compose(SCENES, out, "long", self.tmp / "w", audio=files, captions=False)
        info = probe(out)
        self.assertEqual((info["width"], info["height"]), (1920, 1080))
        self.assertAlmostEqual(info["seconds"], 2.5 + 2 * 0.35, delta=0.5)
        self.assertTrue(info["has_audio"])

    def test_single_audio(self):
        f = self.tmp / "all.wav"
        tone(f, 2.0)
        out = self.tmp / "c.mp4"
        compose(SCENES, out, "short", self.tmp / "w", audio=f)
        self.assertAlmostEqual(probe(out)["seconds"], 2.0, delta=0.5)


FAKE = textwrap.dedent('''
    import json, subprocess, sys, time
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        r, mid = None, m["id"]
        if m["method"] == "initialize":
            r = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake"}}
        elif m["method"] == "tools/list":
            r = {"tools": [{"name": "render"}]}
        elif m["method"] == "tools/call":
            a = m["params"]["arguments"]
            n = m["params"]["name"]
            if n == "boom":
                r = {"isError": True, "content": [{"type": "text", "text": "kaboom"}]}
            elif n == "rpcerr":
                print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -1, "message": "nope"}}), flush=True)
                continue
            elif n == "hang":
                time.sleep(30)
            elif n == "nofile":
                r = {"content": [{"type": "text", "text": "done"}]}
            else:
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=%dx%d:d=0.5" % (a["width"], a["height"]), "-pix_fmt", "yuv420p", a["output_path"]], check=True)
                r = {"content": [{"type": "text", "text": "ok"}]}
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": r}), flush=True)
''')


class McpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.script = self.tmp / "fake.py"
        self.script.write_text(FAKE)

    def client(self, t=10):
        return McpClient(sys.executable, [str(self.script)], t)

    def test_tools_and_errors(self):
        with self.client() as c:
            self.assertEqual(c.list_tools()[0]["name"], "render")
            self.assertEqual(c.call_tool("nofile", {})["text"], "done")
            with self.assertRaisesRegex(McpError, "kaboom"):
                c.call_tool("boom", {})
            with self.assertRaisesRegex(McpError, "nope"):
                c.call_tool("rpcerr", {})
        self.assertIsNone(c.proc)

    def test_timeout_kills(self):
        with self.client(1) as c:
            proc = c.proc
            with self.assertRaisesRegex(McpError, "timed out"):
                c.call_tool("hang", {})
        self.assertIsNotNone(proc.poll())

    def test_missing_command(self):
        with self.assertRaises(McpError):
            McpClient("definitely-not-a-command-xyz", [], 2).__enter__()
        with self.assertRaises(McpError):
            McpClient("", [], 2).__enter__()

    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def test_render_clips(self):
        cfg = {"command": sys.executable, "args": [str(self.script)], "tool": "render", "timeout_s": 30}
        clips = render_clips(cfg, SCENES, "short", self.tmp / "w")
        self.assertEqual(len(clips), 2)
        self.assertEqual(probe(clips[0])["width"], 1080)
        out = self.tmp / "m.mp4"
        compose(SCENES, out, "short", self.tmp / "w2", clips=clips)
        self.assertEqual(probe(out)["height"], 1920)

    def test_render_clips_missing_file(self):
        cfg = {"command": sys.executable, "args": [str(self.script)], "tool": "nofile", "timeout_s": 10}
        with self.assertRaises(McpError):
            render_clips(cfg, SCENES, "short", self.tmp / "w")


if __name__ == "__main__":
    unittest.main()
