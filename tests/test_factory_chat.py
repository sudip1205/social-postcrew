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
            (root / "out" / "gil-explained-hyperframes.jpg").write_bytes(b"jpg")
            (root / "out" / "gil-explained.srt").write_text("1")
            (root / "out" / "gil-explained-two-hyperframes.mp4").write_bytes(b"other episode")
            factory_chat.delete_video(ws, "gil-explained")
            self.assertEqual(sorted(f.name for f in (root / "out").iterdir() if f.is_file()), ["gil-explained-two-hyperframes.mp4"])   # only this episode's files
            self.assertTrue((ep / "youtube.json").exists())                                                              # its script stays
            with self.assertRaises(ValueError):
                factory_chat.delete_video(ws, "gil-explained")

    def test_a_manual_plan_fills_the_message_and_its_video_marks_the_plan_made(self):
        from postcrew import monthly
        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls):
            item = monthly.add_manual(ws, "youtube", "Two Sum with a hash map", "Find two numbers that add to a target", "draw the map filling",
                                      "short", "", "", [])
            self.assertEqual([p["id"] for p in factory_chat.plans(ws)], [item["id"]])
            r = factory_chat.plan_prompt(ws, item["id"])
            self.assertTrue(r["slug"].startswith(f"plan-{item['id']}-two-sum"))
            self.assertIn("Find two numbers that add to a target", r["text"])
            self.assertIn("How I want it made: draw the map filling", r["text"])
            self.assertIn(f"episodes/{r['slug']}/", r["text"])
            ep = root / "episodes" / r["slug"]
            ep.mkdir(parents=True)
            (ep / "youtube.json").write_text(json.dumps({"title": "Two Sum in 45 seconds", "description": "d", "tags": []}))
            (root / "out").mkdir()
            (root / "out" / f"{r['slug']}-hyperframes.mp4").write_bytes(b"mp4")
            post = factory_chat.queue_video(ws, r["slug"], "2030-01-05")["post"]
            self.assertEqual(post["plan_id"], item["id"])
            self.assertEqual(factory_chat.plans(ws), [])   # made: it leaves the list
            with self.assertRaises(ValueError):
                factory_chat.plan_prompt(ws, "nope0000")


if __name__ == "__main__":
    unittest.main()


class FactoryHttpTests(unittest.TestCase):
    """Over real HTTP: Move to Queue once hung forever (its route read the request body twice)."""

    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        from postcrew.studio.server import Studio, make_handler
        self.tw = TempWorkspace()
        self.ws = self.tw.__enter__()
        studio = Studio(self.ws, 0)
        handler = make_handler(studio)
        handler.log_message = lambda *a: None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        studio.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{studio.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tw.__exit__()

    def post(self, path, body):
        import urllib.error
        import urllib.request
        r = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                   headers={"Content-Type": "application/json", "X-Postcrew": "1"})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_move_to_queue_answers_and_uses_the_details_you_checked(self):
        with fake_factory(self.ws) as (root, _calls):
            ep = root / "episodes" / "zoom-sfu"
            ep.mkdir(parents=True)
            (ep / "youtube.json").write_text(json.dumps({"title": "Old title", "description": "Old", "tags": ["a"], "categoryId": "28"}))
            (root / "out").mkdir()
            (root / "out" / "zoom-sfu-hyperframes.mp4").write_bytes(b"mp4")
            code, out = self.post("/api/factory/queue", {"slug": "zoom-sfu", "date": "2030-01-05", "title": "SFU vs MCU in 60 seconds",
                                                         "description": "How Zoom mixes video.", "tags": "webrtc, video calls, sfu"})
            self.assertEqual(code, 200, out)
            yt = out["post"]["youtube"]
            self.assertEqual((yt["title"], yt["description"], yt["tags"]), ("SFU vs MCU in 60 seconds", "How Zoom mixes video.",
                                                                              ["webrtc", "video calls", "sfu"]))
            saved = json.loads((ep / "youtube.json").read_text())
            self.assertEqual((saved["title"], saved["categoryId"]), ("SFU vs MCU in 60 seconds", "28"))   # saved back, other keys kept
            code, out = self.post("/api/factory/queue", {"slug": "zoom-sfu", "date": "2030-01-05", "title": ""})
            self.assertEqual(code, 400)
            self.assertIn("title", out["error"])


class FactoryListAndReferenceTests(unittest.TestCase):
    def setUp(self):
        FakeProc.calls = []

    def test_a_queued_video_leaves_the_factory_list(self):
        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls):
            ep = root / "episodes" / "gil"
            ep.mkdir(parents=True)
            (ep / "youtube.json").write_text(json.dumps({"title": "GIL", "description": "d", "tags": []}))
            (root / "out").mkdir()
            (root / "out" / "gil-hyperframes.mp4").write_bytes(b"mp4")
            (root / "out" / "gil-hyperframes.jpg").write_bytes(b"jpg")
            out = factory_chat.queue_video(ws, "gil", "2030-01-05")
            self.assertEqual(out["videos"], [])
            self.assertEqual(len(ws.queue()), 1)
            self.assertTrue((root / "out" / "queued" / "gil-hyperframes.mp4").exists())

    def test_a_reference_video_with_a_comment_is_sent_to_claude_to_learn(self):
        from postcrew import factory_refs

        def fake_run(cmd, **kw):
            if cmd[0] == "ffprobe":
                return mock.Mock(stdout="20.0\n", returncode=0)
            Path(cmd[-1]).write_bytes(b"jpg")   # ffmpeg frame
            return mock.Mock(stdout="", returncode=0)

        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls), \
                mock.patch.object(factory_refs.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(ValueError):
                factory_refs.add_upload(ws, "notes.txt", "", io.BytesIO(b"x"), 1)
            r = factory_refs.add_upload(ws, "liked.mp4", "", io.BytesIO(b"v" * 10), 10)["reference"]
            self.assertEqual((r["frames"], r["seconds"]), (factory_refs.FRAMES, 20.0))
            self.assertTrue(str(factory_refs.folder(ws)).startswith(str(root.parent)))
            with self.assertRaises(ValueError):   # nothing to learn yet
                factory_chat.teach(ws, r["id"], runner=FakeProc)
            factory_refs.comment(ws, r["id"], "the title pops in word by word")
            factory_chat.teach(ws, r["id"], runner=FakeProc)
            wait_idle()
            msg = factory_chat.view(ws)["messages"][0]["text"]
            self.assertIn("the title pops in word by word", msg)
            self.assertIn("frames/01.jpg", msg)
            self.assertTrue(factory_refs.listing(ws)[0]["learned"])
            factory_refs.delete(ws, r["id"])
            self.assertEqual(factory_refs.listing(ws), [])
