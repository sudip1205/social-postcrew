"""The YouTube crew is the owner's Shorts factory: Claude Code writes the episode in the factory, `npm run make` renders it, and the
Publisher queues it. The factory and Claude Code are faked here (no AI, no render)."""
import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from helpers import TempWorkspace  # noqa: E402

from postcrew.agents import shorts  # noqa: E402
from postcrew.crew import run_crew  # noqa: E402

DAY = date(2026, 11, 3)


@contextlib.contextmanager
def fake_factory(ws, fail_render=False, write=True):
    """A shorts-factory folder and a fake subprocess.run for `claude -p` (writes the episode) and `npm run make` (writes the video)."""
    root = Path(tempfile.mkdtemp(prefix="factory-")) / "shorts-factory"
    (root / "episodes").mkdir(parents=True)
    (root / "package.json").write_text("{}")
    cfg = ws.config()
    cfg["platforms"]["youtube"]["video"]["factory_path"] = str(root)
    cfg["platforms"]["youtube"]["enabled"] = True
    ws.save_config(cfg)
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        if cmd[0].endswith("claude") or "/claude" in cmd[0]:
            slug = kw["input"].split("episodes/")[1].split("/")[0]
            ep = root / "episodes" / slug
            ep.mkdir(parents=True, exist_ok=True)
            if write:
                (ep / "script.json").write_text(json.dumps({"scenes": [{"type": "hook", "say": "Ever wondered why?"}, {"type": "cta", "say": "Follow."}]}))
                (ep / "youtube.json").write_text(json.dumps({"title": "Why it works", "description": "A short explainer.", "tags": ["python", "tips"]}))
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"subtype": "success", "is_error": False, "total_cost_usd": 0.42,
                                                                   "num_turns": 7, "result": "DONE"}), "")
        if cmd[:3] == ["npm", "run", "make"]:
            if fail_render:
                return subprocess.CompletedProcess(cmd, 1, "", "Kokoro did not answer")
            slug = cmd[-1].split("/")[-1]
            (root / "out").mkdir(exist_ok=True)
            (root / "out" / f"{slug}-hyperframes.mp4").write_bytes(b"mp4")
            (root / "out" / f"{slug}-hyperframes.jpg").write_bytes(b"jpg")
            (root / "out" / f"{slug}.srt").write_text("1\n")
            return subprocess.CompletedProcess(cmd, 0, "done", "")
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, "58.4\n", "")
        raise AssertionError(f"unexpected command {cmd}")

    try:
        with mock.patch.object(shorts.subprocess, "run", side_effect=run):
            yield root, calls
    finally:
        shutil.rmtree(root.parent, ignore_errors=True)


@mock.patch("postcrew.agents.credentials.check_claude", new=lambda *a, **k: {"state": "ok", "message": "Claude Code is ready"})
class ShortsCrewTests(unittest.TestCase):
    def test_the_crew_is_the_factory(self):
        from postcrew.agents.supervisor import crew_for
        self.assertEqual([a.id for a in crew_for("youtube")], ["credentials", "topic", "writer", "media", "publisher"])

    def test_a_short_is_written_in_the_factory_rendered_and_queued(self):
        with TempWorkspace() as ws, fake_factory(ws) as (root, calls):
            res = run_crew(ws, DAY, "short-tip", platform="youtube")
            self.assertTrue(res["ok"], res)
            claude, make = calls[0], calls[1]
            self.assertEqual(claude[1]["cwd"], str(root.parent))       # started in the factory's workspace: its CLAUDE.md and skill apply
            self.assertIn("explainer-short-style", claude[1]["input"])
            self.assertIn("Do NOT render", claude[1]["input"])
            self.assertEqual(make[0][:3], ["npm", "run", "make"])
            self.assertEqual(make[1]["cwd"], str(root))
            post = ws.queue()[0]
            self.assertEqual((post["platform"], post["youtube"]["title"], post["youtube"]["tags"]), ("youtube", "Why it works", ["python", "tips"]))
            self.assertEqual(post["youtube"]["seconds"], 58.4)
            self.assertTrue((ws.root / post["media"]).exists())
            self.assertTrue(post["poster_image"].endswith(".jpg"))
            self.assertAlmostEqual(res["cost_usd"], 0.42)

    def test_a_planned_topic_is_handed_to_the_writer(self):
        with TempWorkspace() as ws, fake_factory(ws) as (_root, calls):
            planned = {"category": "short-tip", "topic": "Python default arguments", "angle": "the mutable trap"}
            with mock.patch("postcrew.agents.topic.planned_for", return_value=planned):
                run_crew(ws, DAY, "short-tip", platform="youtube")
            self.assertIn("Topic: Python default arguments", calls[0][1]["input"])
            self.assertIn("Angle: the mutable trap", calls[0][1]["input"])
            self.assertIn(f"episodes/{DAY.isoformat()}-python-default-arguments/", calls[0][1]["input"])

    def test_a_failed_render_fails_the_run_and_queues_nothing(self):
        with TempWorkspace() as ws, fake_factory(ws, fail_render=True):
            res = run_crew(ws, DAY, "short-tip", platform="youtube")
            self.assertFalse(res["ok"])
            self.assertEqual(ws.queue(), [])

    def test_no_factory_stops_at_once(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"]["video"]["factory_path"] = "/nonexistent/shorts-factory"
            ws.save_config(cfg)
            res = run_crew(ws, DAY, "short-tip", platform="youtube")
            self.assertFalse(res["ok"])
            self.assertIn("Shorts factory is not at", " ".join(res["problems"]))


if __name__ == "__main__":
    unittest.main()
