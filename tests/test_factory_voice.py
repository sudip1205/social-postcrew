"""Your own voice in a Factory video: a whole take is split into scenes by its words; one scene can be replaced; the video is made again."""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from helpers import TempWorkspace  # noqa: E402
import contextlib  # noqa: E402


@contextlib.contextmanager
def fake_factory(ws):
    """A bare factory folder (real ffmpeg runs; only whisper and the render are faked)."""
    root = Path(tempfile.mkdtemp()) / "shorts-factory"
    root.mkdir(parents=True)
    (root / "package.json").write_text("{}")
    cfg = ws.config()
    cfg["platforms"]["youtube"]["video"]["factory_path"] = str(root)
    ws.save_config(cfg)
    try:
        yield root, []
    finally:
        shutil.rmtree(root.parent, ignore_errors=True)

from postcrew import factory_voice  # noqa: E402


def tone(seconds):
    d = Path(tempfile.mkdtemp())
    f = d / "take.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=220:d={seconds}", "-c:a", "aac", str(f)], check=True)
    return f.read_bytes()


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class FactoryVoiceTests(unittest.TestCase):
    def episode(self, root):
        ep = root / "episodes" / "gil"
        ep.mkdir(parents=True)
        (ep / "script.json").write_text(json.dumps({"title": "GIL", "voice": "am_echo", "scenes": [
            {"type": "hook", "text": "one two three four"}, {"type": "flow", "text": "five six seven eight nine ten"},
            {"type": "cta", "text": "eleven twelve"}]}))
        return ep

    def test_a_whole_take_is_split_into_scenes_at_the_pauses(self):
        heard = [{"w": w, "s": s, "e": s + 0.3} for w, s in zip("one two three four five six seven eight nine ten eleven twelve".split(),
                                                                  [0.2, 0.6, 1.0, 1.4, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6, 5.8, 6.2])]
        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls):
            ep = self.episode(root)
            data = tone(7)
            with mock.patch.object(factory_voice, "_has_whisper", return_value=True), \
                    mock.patch.object(factory_voice, "_words", return_value=heard):
                r = factory_voice.upload(ws, "gil", None, "take.m4a", io.BytesIO(data), len(data))
            self.assertEqual((r["saved"], r["own"]), ([0, 1, 2], 3))
            w1 = json.loads((ep / "voice" / "scene1.words.json").read_text())
            self.assertEqual(w1[0]["w"], "five")                     # cut in the pause before "five"
            self.assertLess(w1[0]["s"], 0.2)                          # its times start from its own clip
            self.assertAlmostEqual(r["scenes"][1]["seconds"], 2.48, delta=0.15)
            script = json.loads((ep / "script.json").read_text())
            self.assertEqual((script["voice"], script["voice_kokoro"]), ("own", "am_echo"))
            factory_voice.clear(ws, "gil", 1)
            self.assertFalse((ep / "voice" / "scene1.wav").exists())
            factory_voice.clear(ws, "gil")
            self.assertEqual(json.loads((ep / "script.json").read_text())["voice"], "am_echo")   # Kokoro again

    def test_one_scene_can_be_replaced_and_bad_files_are_refused(self):
        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls):
            ep = self.episode(root)
            with self.assertRaises(ValueError):
                factory_voice.upload(ws, "gil", 0, "notes.txt", io.BytesIO(b"x"), 1)
            data = tone(2)
            with mock.patch.object(factory_voice, "_words", return_value=[{"w": "one", "s": 0.1, "e": 0.4}]):
                factory_voice.upload(ws, "gil", "2", "scene.m4a", io.BytesIO(data), len(data))
            self.assertTrue((ep / "voice" / "scene2.wav").exists())
            with self.assertRaises(ValueError):
                factory_voice.upload(ws, "gil", 9, "scene.m4a", io.BytesIO(data), len(data))

    def test_making_it_again_runs_the_factory_for_that_episode(self):
        calls = []
        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls):
            self.episode(root)
            factory_voice._whisper_py["p"] = None
            factory_voice.render(ws, "gil", runner=lambda cmd, **kw: calls.append(cmd) or mock.Mock(returncode=0, stdout="ok", stderr=""))
            for _ in range(200):
                if factory_voice._render["done"]:
                    break
                time.sleep(0.01)
            self.assertEqual(calls[0][-2:], ["episodes/gil", "--allow-repeat"])
            self.assertIsNone(factory_voice.view(ws, "gil")["render"]["error"])


if __name__ == "__main__":
    unittest.main()
