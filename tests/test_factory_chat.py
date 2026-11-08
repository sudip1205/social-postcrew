"""The Factory chat: Claude Code in the Shorts factory, carried on from message to message; videos it makes can be queued."""
import io
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from helpers import TempWorkspace  # noqa: E402
from test_shorts import fake_factory  # noqa: E402

from postcrew import factory_chat  # noqa: E402


class FakeProc:
    calls = []

    def __init__(self, cmd, cwd=None, **kw):
        FakeProc.calls.append({"cmd": cmd, "cwd": cwd})
        self.stdin = io.StringIO()
        lines = [{"type": "system", "subtype": "init", "session_id": "s-1"},
                 {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "/x/SKILL.md"}}]}},
                 {"type": "assistant", "message": {"content": [{"type": "text", "text": "Updated SKILL.md: captions moved up."}]}},
                 {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.12, "session_id": "s-1"}]
        self.stdout = io.StringIO("\n".join(json.dumps(x) for x in lines) + "\n")
        self.stderr = io.StringIO("")
        self.returncode = 0

    def wait(self):
        return 0

    def poll(self):
        return 0


def wait_idle():
    for _ in range(200):
        if not factory_chat.busy():
            return
        time.sleep(0.01)


class FactoryChatTests(unittest.TestCase):
    def setUp(self):
        FakeProc.calls = []

    def test_a_message_runs_claude_in_the_factory_and_the_chat_carries_on(self):
        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls):
            factory_chat.send(ws, "From now on, captions higher", runner=FakeProc)
            wait_idle()
            st = factory_chat.view(ws)
            self.assertEqual([m["role"] for m in st["messages"]], ["user", "tool", "assistant", "system"])
            self.assertEqual(st["messages"][1]["text"], "Edit SKILL.md")
            self.assertTrue(st["session"])
            self.assertEqual(FakeProc.calls[0]["cwd"], str(root.parent))   # its CLAUDE.md and skill apply
            self.assertNotIn("--resume", FakeProc.calls[0]["cmd"])
            factory_chat.send(ws, "and a bit slower", runner=FakeProc)
            wait_idle()
            cmd = FakeProc.calls[1]["cmd"]
            self.assertEqual(cmd[cmd.index("--resume") + 1], "s-1")
            factory_chat.reset(ws)
            self.assertEqual(factory_chat.view(ws)["messages"], [])

    def test_an_empty_message_or_a_missing_factory_is_refused(self):
        with TempWorkspace() as ws:
            with self.assertRaises(ValueError):
                factory_chat.send(ws, "  ", runner=FakeProc)
            cfg = ws.config()
            cfg["platforms"]["youtube"]["video"]["factory_path"] = "/nonexistent/shorts-factory"
            ws.save_config(cfg)
            with self.assertRaises(ValueError):
                factory_chat.send(ws, "hello", runner=FakeProc)

    def test_a_video_made_in_the_chat_can_be_queued(self):
        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls):
            ep = root / "episodes" / "gil-explained"
            ep.mkdir(parents=True)
            (ep / "youtube.json").write_text(json.dumps({"title": "The GIL in 50 seconds", "description": "Why.", "tags": ["python"]}))
            (root / "out").mkdir()
            (root / "out" / "gil-explained-hyperframes.mp4").write_bytes(b"mp4")
            vids = factory_chat.videos(ws)
            self.assertEqual((vids[0]["slug"], vids[0]["title"], vids[0]["has_meta"]), ("gil-explained", "The GIL in 50 seconds", True))
            post = factory_chat.queue_video(ws, "gil-explained", "2030-01-05")["post"]
            self.assertEqual((post["youtube"]["title"], post["date"], post["platform"]), ("The GIL in 50 seconds", "2030-01-05", "youtube"))
            self.assertEqual(len(ws.queue()), 1)
            with self.assertRaises(ValueError):
                factory_chat.queue_video(ws, "../etc", "2030-01-05")


if __name__ == "__main__":
    unittest.main()
