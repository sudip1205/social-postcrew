"""The Factory chat: Claude Code in the Shorts factory, carried on from message to message; videos it makes can be queued."""
import io
import json
import sys
import tempfile
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


class StudyTogetherTests(unittest.TestCase):
    def test_several_references_are_studied_together_for_their_pattern(self):
        from postcrew import factory_refs

        def fake_run(cmd, **kw):
            if cmd[0] == "ffprobe":
                return mock.Mock(stdout="30.0\n", returncode=0)
            Path(cmd[-1]).write_bytes(b"jpg")
            return mock.Mock(stdout="", returncode=0)

        FakeProc.calls = []
        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls), \
                mock.patch.object(factory_refs.subprocess, "run", side_effect=fake_run):
            a = factory_refs.add_upload(ws, "a.mp4", "big captions", io.BytesIO(b"v"), 1)["reference"]["id"]
            b = factory_refs.add_upload(ws, "b.mp4", "", io.BytesIO(b"v"), 1)["reference"]["id"]
            with self.assertRaises(ValueError):
                factory_refs.lesson(ws, [])
            factory_chat.teach(ws, [a, b], note="how they open", runner=FakeProc)
            wait_idle()
            msg = factory_chat.view(ws)["messages"][0]["text"]
            for part in ("these 2 reference videos", "pattern", "Video 1:", "Video 2:", "big captions", "how they open"):
                self.assertIn(part, msg)
            self.assertTrue(all(r["learned"] for r in factory_refs.listing(ws)))


class SkillCopyTests(unittest.TestCase):
    """Claude Code never lets the chat write inside .claude/: it edits skill-edit/, and the Studio copies the change into the skill."""

    def test_a_skill_edit_made_in_the_working_copy_reaches_the_skill(self):
        with TempWorkspace() as ws, fake_factory(ws) as (root, _calls):
            real = root.parent / ".claude" / "skills" / "explainer-short-style"
            (real / "references").mkdir(parents=True, exist_ok=True)
            (real / "SKILL.md").write_text("old rules\n")

            class EditingProc(FakeProc):
                def __init__(self, cmd, cwd=None, **kw):
                    work = Path(cwd) / "skill-edit" / "explainer-short-style"
                    assert (work / "SKILL.md").read_text() == "old rules\n"   # a fresh copy is ready before Claude starts
                    (work / "SKILL.md").write_text("old rules\nmore motion types\n")
                    (work / "references" / "motion-groups.md").write_text("groups\n")
                    super().__init__(cmd, cwd, **kw)

            factory_chat.send(ws, "Use more kinds of motion graphics. Update the skill.", runner=EditingProc)
            wait_idle()
            self.assertIn("more motion types", (real / "SKILL.md").read_text())
            self.assertEqual((real / "references" / "motion-groups.md").read_text(), "groups\n")
            cmd = EditingProc.calls[-1]["cmd"]
            self.assertIn("edit its files in .claude/skills/explainer-short-style/ directly", cmd[cmd.index("--append-system-prompt") + 1])
            self.assertIn("skill_hook.py", cmd[cmd.index("--settings") + 1])
            self.assertTrue(any(m["text"].startswith("Skill updated") for m in factory_chat.view(ws)["messages"]))


class SkillHookTests(unittest.TestCase):
    """The live hook: Claude's Edit/Write on .claude/skills/... goes to skill-edit/ and lands in the skill at once."""

    def hook(self, mode, base, event):
        import subprocess, sys as _sys
        script = Path(factory_chat.skill_hook.__file__)
        r = subprocess.run([_sys.executable, str(script), mode, str(base)], input=json.dumps(event), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def test_an_edit_of_the_skill_is_redirected_and_saved_at_once(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            real = base / ".claude" / "skills" / "explainer-short-style"
            real.mkdir(parents=True)
            (real / "SKILL.md").write_text("rule one\n")
            ev = {"tool_name": "Edit", "cwd": str(base / "shorts-factory"),
                  "tool_input": {"file_path": str(real / "SKILL.md"), "old_string": "rule one", "new_string": "rule two"}}
            out = self.hook("pre", base, ev)["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "allow")
            work = Path(out["updatedInput"]["file_path"])
            self.assertEqual(work, (base / "skill-edit" / "explainer-short-style" / "SKILL.md").resolve())
            self.assertEqual(work.read_text(), "rule one\n")   # the skill's current text, ready to edit
            self.assertEqual(out["updatedInput"]["new_string"], "rule two")
            work.write_text("rule two\n")   # what Claude's Edit does
            self.hook("post", base, dict(ev, tool_input=out["updatedInput"]))
            self.assertEqual((real / "SKILL.md").read_text(), "rule two\n")

    def test_a_new_reference_file_is_written_into_the_skill(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / ".claude" / "skills" / "explainer-short-style").mkdir(parents=True)
            f = base / ".claude" / "skills" / "explainer-short-style" / "references" / "pacing.md"
            ev = {"tool_name": "Write", "cwd": str(base), "tool_input": {"file_path": str(f), "content": "slow\n"}}
            work = Path(self.hook("pre", base, ev)["hookSpecificOutput"]["updatedInput"]["file_path"])
            work.write_text("slow\n")
            self.hook("post", base, ev)
            self.assertEqual(f.read_text(), "slow\n")

    def test_other_files_are_left_to_claude_code(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            for path in (base / "shorts-factory" / "episodes" / "x" / "script.json", base / ".claude" / "settings.json",
                         base / ".claude" / "skills" / "explainer-short-style" / ".." / ".." / "settings.json"):
                self.assertIsNone(self.hook("pre", base, {"tool_name": "Write", "cwd": str(base), "tool_input": {"file_path": str(path)}}))
            self.assertIsNone(self.hook("pre", base, {"tool_name": "Bash", "tool_input": {"command": "ls"}}))


class AllowedCommandTests(unittest.TestCase):
    def test_path_rules_use_the_wildcard_form(self):
        # Claude Code 2.1 matches "Bash(x:*)" only at a word boundary: "Bash(python3 algo/:*)" never allowed python3 algo/x.py
        from postcrew.agents.shorts import WRITER_TOOLS
        for rule in factory_chat.TOOLS + WRITER_TOOLS:
            self.assertNotRegex(rule, r"/:\*\)$", rule)
        self.assertIn("Bash(python3 algo/*)", factory_chat.TOOLS)
