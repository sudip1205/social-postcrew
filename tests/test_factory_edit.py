"""The Factory's video editor (owner, 2026-11-23): after Make video the video waits in the editor (never uploaded), changes by hand
or with an AI command for picked frames and sections, render again, and only the owner's Approve makes it ready for upload."""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from postcrew import factory_edit, factory_plans  # noqa: E402
from tests.helpers import TempWorkspace  # noqa: E402

SLUG = "2026-11-23-active-passive"
TIMING = {"W": 1080, "H": 1920, "long": False, "duration": 20.0, "end": 16.0,
          "beats": [{"t0": 0, "t1": 8.0, "say": "Two servers, one works."}, {"t0": 8.0, "t1": 16.0, "say": "The spare takes over."}],
          "cta": {"t0": 16.0, "t1": 20.0, "say": "Follow."}}


def _wait(slug):
    for _ in range(500):
        j = factory_edit._jobs.get(slug)
        if j and j.get("done"):
            return j
        time.sleep(0.02)
    raise AssertionError("the editor job did not finish")


class EditorTests(unittest.TestCase):
    def setUp(self):
        factory_edit._jobs.clear()

    def _setup(self, ws):
        root = ws.root / "shorts-factory"
        ep = root / "episodes" / SLUG
        (ep / "build-iso").mkdir(parents=True)
        (root / "out").mkdir()
        cfg = ws.config()
        cfg["platforms"]["youtube"]["video"]["factory_path"] = str(root)
        ws.save_config(cfg)
        (ep / "script.json").write_text(json.dumps({"style": "iso", "beats": [{"say": b["say"]} for b in TIMING["beats"]]}))
        (ep / "explainer.js").write_text("function explainer(ctx, W, H_, t) { nameOn(ctx, P, [0,0,0,2,2,2], 'Server A'); }\n")
        (ep / "build-iso" / "page.html").write_text(
            f'<html><head><style>canvas{{display:block}}</style></head><body><script src="file://{root.resolve()}/styles/iso-pastel/kit.js"></script>'
            f'<script>window.TIMING = {json.dumps(TIMING)}; const TIMING = window.TIMING;</script>'
            f'<script src="file://{root.resolve()}/episodes/{SLUG}/explainer.js"></script></body></html>')
        (ws.root / "media").mkdir(exist_ok=True)
        (ws.root / "media" / "p1.mp4").write_bytes(b"old")
        ws.save_queue([{"id": "p1", "platform": "youtube", "status": "editing", "media": "media/p1.mp4", "topic": "Active passive",
                        "youtube": {"episode": SLUG}}])
        with factory_plans._lock:
            factory_plans._save(ws, {"items": [{"id": "pl1", "title": "Active passive", "state": "editing", "slug": SLUG, "post_id": "p1"}]})
        return root, ep

    def test_the_editor_shows_the_sections_and_serves_the_page_from_the_studio(self):
        with TempWorkspace() as ws:
            root, ep = self._setup(ws)
            v = factory_edit.view(ws, SLUG)
            self.assertTrue(v["ready"])
            self.assertEqual([s["say"] for s in v["sections"]], ["Two servers, one works.", "The spare takes over."])
            self.assertEqual(v["post"], {"id": "p1", "status": "editing"})
            html = factory_edit.page(ws, SLUG)
            self.assertNotIn("file://", html)
            self.assertIn("/factory-files/styles/iso-pastel/kit.js?v=", html)
            self.assertIn(f"/factory-files/episodes/{SLUG}/explainer.js?v=", html)
            f, _ = factory_edit.file_path(ws, f"episodes/{SLUG}/explainer.js")
            self.assertEqual(f.name, "explainer.js")
            for bad in (f"episodes/{SLUG}/script.json", "../secrets.json", f"episodes/{SLUG}/voice/scene0.wav"):
                with self.assertRaises(KeyError):
                    factory_edit.file_path(ws, bad)
            with self.assertRaises(ValueError):
                factory_edit.view(ws, "../../etc")

    def test_hand_edits_are_cleaned_saved_and_mark_the_video_changed(self):
        with TempWorkspace() as ws:
            root, ep = self._setup(ws)
            v = factory_edit.save_edits(ws, SLUG, {"texts": {"Server A": "Main server", "same": "same"}, "hide": ["  1 s down "],
                                                    "moves": {"missed 1 of 3": [40.4, -12], "tiny": [0.2, 0], "bad": ["x", 1]}})
            self.assertEqual(json.loads((ep / "edits.json").read_text()),
                             {"texts": {"Server A": "Main server"}, "hide": ["1 s down"], "moves": {"missed 1 of 3": [40, -12]}})
            self.assertTrue(v["changed"])
            with self.assertRaisesRegex(ValueError, "Render the video first"):
                factory_edit.approve(ws, SLUG)

    def test_an_ai_change_is_kept_with_the_drawing_before_it_and_can_be_undone(self):
        with TempWorkspace() as ws:
            root, ep = self._setup(ws)
            before = (ep / "explainer.js").read_text()
            prompts = []

            def fake_claude(ws_, prompt, cwd):
                prompts.append(prompt)
                (ep / "explainer.js").write_text(before + "// bigger server\n")
                (ep / "script.json").write_text("{}")   # not the AI's to change: put back
                return "I made the server bigger in section 2.", 0.12
            with mock.patch.object(factory_edit, "_claude", fake_claude), mock.patch.object(factory_edit, "_check", lambda ws_, ep_: []):
                factory_edit.ask(ws, SLUG, "make the server bigger", frames=[{"t": 9.5, "image": "data:image/jpeg;base64,/9j/AA=="}], sections=[1, 7])
                j = _wait(SLUG)
            self.assertIsNone(j["error"])
            self.assertIn("section 2 (8.0 to 16.0 s", prompts[0])
            self.assertIn(f"episodes/{SLUG}/edit/frames/f-0009.50.jpg", prompts[0])
            self.assertTrue((ep / "edit" / "frames" / "f-0009.50.jpg").exists())
            self.assertIn("bigger server", (ep / "explainer.js").read_text())
            self.assertIn("beats", (ep / "script.json").read_text())
            v = factory_edit.view(ws, SLUG)
            self.assertEqual(v["history"][0]["result"], "I made the server bigger in section 2.")
            self.assertEqual(v["history"][0]["sections"], [2])
            with mock.patch.object(factory_edit, "_check", lambda ws_, ep_: []):
                factory_edit.undo(ws, SLUG)
                _wait(SLUG)
            self.assertEqual((ep / "explainer.js").read_text(), before)
            self.assertTrue(factory_edit.view(ws, SLUG)["history"][0]["undone"])

    def test_render_replaces_the_queue_copy_and_only_approve_makes_it_ready_for_upload(self):
        with TempWorkspace() as ws:
            root, ep = self._setup(ws)
            factory_edit.save_edits(ws, SLUG, {"texts": {"Server A": "Main"}})

            def fake_run(cmd, **kw):
                if cmd[0] == "npm":
                    (root / "out" / f"{SLUG}-hyperframes.mp4").write_bytes(b"new video")
                return mock.Mock(returncode=0, stdout="12.5\n", stderr="")
            with mock.patch.object(factory_edit.subprocess, "run", fake_run):
                factory_edit.render(ws, SLUG)
                self.assertIsNone(_wait(SLUG)["error"])
            self.assertEqual((ws.root / "media" / "p1.mp4").read_bytes(), b"new video")
            self.assertEqual(ws.queue()[0]["status"], "editing")
            v = factory_edit.approve(ws, SLUG)
            self.assertEqual(ws.queue()[0]["status"], "approved")
            self.assertEqual(factory_plans.get(ws, "pl1")["state"], "made")
            self.assertEqual(v["plan_state"], "made")
            factory_edit.reopen(ws, SLUG)
            self.assertEqual(ws.queue()[0]["status"], "editing")
            self.assertEqual(factory_plans.get(ws, "pl1")["state"], "editing")

    def test_a_video_in_the_editor_is_never_due_for_upload(self):
        from postcrew.agents import publisher
        self.assertNotIn("editing", publisher.DUE)

    def test_only_a_factory_plans_animated_video_goes_to_the_editor(self):
        from postcrew.agents import publisher
        with TempWorkspace() as ws:
            root, ep = self._setup(ws)
            ctx = mock.Mock(options={"plan_id": "pl1"}, outputs={"writer": {"slug": SLUG}}, cfg=factory_plans._cfg(ws))
            self.assertTrue(publisher._editable(ctx))
            ctx.options = {}
            self.assertFalse(publisher._editable(ctx))   # a scheduled crew run: the Queue's approval as before
            ctx.options, ctx.outputs = {"plan_id": "pl1"}, {"writer": {"slug": "a-story-video"}}
            self.assertFalse(publisher._editable(ctx))   # no animation to edit frame by frame


if __name__ == "__main__":
    unittest.main()
