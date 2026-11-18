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
def fake_factory(ws, fail_render=False, write=True, desk=False):
    """A shorts-factory folder and a fake subprocess.run for `claude -p` (writes the episode) and `npm run make` (writes the video)."""
    root = Path(tempfile.mkdtemp(prefix="factory-")) / "shorts-factory"
    (root / "episodes").mkdir(parents=True)
    (root / "package.json").write_text("{}")
    from postcrew import factory_styles
    factory_styles.save(ws, ["signal", "code"])   # this fake factory makes HyperFrames Signal episodes (Signal alone uses the Tech Glow canvas engine since 2026-11-15)
    cfg = ws.config()
    cfg["platforms"]["youtube"]["video"]["factory_path"] = str(root)
    cfg["platforms"]["youtube"]["enabled"] = True
    # Factory > Voice holds every video for the owner's approvals (2026-11-16); these tests are about the rest of the run
    cfg["platforms"]["youtube"]["video"]["voice_desk"] = {"enabled": desk}
    ws.save_config(cfg)
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        if cmd[0].endswith("claude") or "/claude" in cmd[0]:
            slug = kw["input"].split("episodes/")[1].split("/")[0]
            ep = root / "episodes" / slug
            ep.mkdir(parents=True, exist_ok=True)
            if write:
                (ep / "script.json").write_text(json.dumps({"style": "story", "hook_options": ["Ever wondered why?", "Two", "Three"], "analogy": {"world": "Max shelves every book by what it is about in his library"},
                                                         "scenes": [{"type": "story", "text": "Ever wondered why?", "beats": [{"do": "walk", "who": "max"}]},
                                                                    {"type": "map", "text": "Follow. " + " ".join(["Each word sits near the words it means."] * 20), "pairs": [{"tech": "Embedding"}]}]}))
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
            self.assertIn("read the current skill from disk", claude[1]["input"])   # every scheduled run reads the skill as it is now
            self.assertIn("Skill", claude[0][claude[0].index("--tools") + 1])
            self.assertEqual(make[0][:3], ["npm", "run", "make"])
            self.assertEqual(make[1]["cwd"], str(root))
            post = ws.queue()[0]
            self.assertEqual((post["platform"], post["youtube"]["title"], post["youtube"]["tags"]), ("youtube", "Why it works", ["python", "tips"]))
            self.assertEqual(post["youtube"]["seconds"], 58.4)
            self.assertTrue((ws.root / post["media"]).exists())
            self.assertTrue(post["poster_image"].endswith(".jpg"))
            self.assertAlmostEqual(res["cost_usd"], 0.42)
            import json as _j
            self.assertEqual(len(_j.loads((ws.runs_dir / res["run_id"] / "writer.json").read_text())["skill"]["fingerprint"]), 10)

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


class StoryLookTests(unittest.TestCase):
    """Owner, 2026-11-12: an explainer Short is a Story video; an algorithm video keeps the Signal look."""

    def test_an_explainer_must_be_a_story_but_an_algorithm_may_not_be(self):
        from postcrew.agents.shorts import ShortsWriter
        w, base = ShortsWriter(), {"title": "t", "scene_count": 3, "words": 180, "long": False, "code_scenes": 0}
        self.assertTrue(any("Story video" in p for p in w.validate(None, dict(base, kind="explainer", style=""))))
        self.assertFalse(w.validate(None, dict(base, kind="explainer", style="story")))
        self.assertFalse(w.validate(None, dict(base, kind="algorithm", style="", code_scenes=1)))
        self.assertFalse(w.validate(None, dict(base, long=True, kind="", style="")))   # long videos keep their wide look
        self.assertFalse(w.validate(None, dict(base, kind="explainer", style="", ticked=["signal"])))   # Story not ticked: blue is right


class StoryNotLectureTests(unittest.TestCase):
    """Owner, 2026-11-12: a Story video acts out an everyday analogy; a lecture with the cast beside a diagram is sent back."""

    def story(self, **kw):
        s = {"style": "story", "analogy": {"world": "Max shelves every book by what it is about so neighbours share a topic"},
             "scenes": [{"type": "story", "text": "Max shelves every book by topic.", "beats": [{"do": "carry", "who": "max"}]},
                        {"type": "story", "text": "Lily wants a rockets book.", "beats": [{"do": "enter", "who": "lily"}]},
                        {"type": "map", "text": "That is an embedding. " + " ".join(["Each word sits near the words it means."] * 20), "pairs": [{"tech": "Embedding"}]}]}
        s.update(kw)
        return s

    def test_a_story_passes_and_a_lecture_is_sent_back(self):
        from postcrew.agents.shorts import story_problems
        self.assertEqual(story_problems(self.story()), [])
        self.assertEqual(story_problems({"style": "signal"}), [])
        bad = self.story(analogy={})
        bad["scenes"][0]["text"] = "The computer gives every word an embedding."
        bad["scenes"][1]["beats"] = [{"do": "point", "who": "lily"}]
        bad["scenes"][0]["beats"] = [{"do": "say", "who": "max"}]
        got = " | ".join(story_problems(bad))
        for want in ("analogy", "computer world", "before the map", "only stands"):
            self.assertIn(want, got)


class FactoryStylesTests(unittest.TestCase):
    """Owner, 2026-11-12: the looks ticked in the Factory are saved and go to the Script Writer and the Factory chat."""

    def test_ticked_looks_are_saved_and_explained(self):
        from postcrew import factory_styles as fs
        with TempWorkspace() as ws:
            self.assertEqual(fs.ticked(ws), ["iso"])   # Isometric Pastel by default (owner, 2026-11-15; was the blue look)
            self.assertEqual(fs.save(ws, ["code", "signal", "nope"]), ["signal", "code"])
            self.assertEqual([o["id"] for o in fs.options(ws) if o["on"]], ["signal", "code"])
            with self.assertRaises(ValueError):
                fs.save(ws, [])
            line = fs.instruction(fs.ticked(ws))
            self.assertIn("Signal (blue)", line); self.assertIn("VS Code", line); self.assertIn("\"styles\": [\"signal\", \"code\"]", line)
            self.assertIn("mixing-styles.md", line)


class ThreeDLookTests(unittest.TestCase):
    """Owner, 2026-11-13: the 3D look makes the whole video by itself, so it is ticked on its own.
    Owner, 2026-11-14: it is rendered by video-engine; the Script Writer writes its storyboard program (scene.js)."""

    def test_3d_is_ticked_alone_and_tells_the_factory_to_use_the_3d_pipeline(self):
        from postcrew import factory_styles as fs
        with TempWorkspace() as ws:
            self.assertEqual(fs.save(ws, ["3d"]), ["3d"])
            self.assertTrue(fs.is_3d(fs.ticked(ws)))
            with self.assertRaises(ValueError):
                fs.save(ws, ["signal", "3d"])
            line = fs.instruction(["3d"])
            self.assertIn('"style": "3d"', line); self.assertIn("video-engine", line); self.assertIn("scene.js", line)
            self.assertFalse(fs.is_3d(["signal"]))

    def _engine(self, d):
        ve = Path(d) / "video-engine"; ve.mkdir()
        (ve / "RULES.md").write_text("# rules"); (ve / "ve.mjs").write_text("")
        return ve

    def test_the_script_writer_writes_the_storyboard_program_for_video_engine(self):
        from postcrew import factory_styles as fs
        with TempWorkspace() as ws, tempfile.TemporaryDirectory() as d:
            fs.save(ws, ["3d"])
            ve, root, ep = self._engine(d), Path(d), Path(d) / "episodes" / "e1"
            beats = [{"say": "How does a hash map find your key so fast? " * 8}, {"say": "It turns the key into a number. " * 8}]
            def fake_claude(ctx, prompt, tools, cwd, add_dirs=()):
                self.assertIn("=== RULES.md (video-engine) ===", prompt); self.assertIn("9:16 Short", prompt)
                self.assertTrue(any("ve.mjs compile" in t for t in tools)); self.assertEqual(Path(cwd), ep)
                (ep / "scene.js").write_text("function build(sb) {}")
                (ep / "youtube.json").write_text(json.dumps({"title": "How a Hash Map Works", "description": "d", "tags": ["hash map"]}))
                return {}
            ctx = mock.Mock(ws=ws, cfg={"video": {"engine_path": str(ve)}}, cat={"label": "Short", "brief": "b", "format": "short"},
                            video={"format": "short", "target_seconds": 55})
            w = shorts.ShortsWriter()
            with mock.patch.object(w, "_claude", side_effect=fake_claude), mock.patch("postcrew.agents.shorts.skill_version", return_value={}), \
                 mock.patch("postcrew.agents.shorts.compile_storyboard", return_value={"errors": [], "storyboard": {"beats": beats}}):
                out = w._plan_3d(ctx, root, ep, "e1", "How a Hash Map Works", {"angle": "one step"})
            self.assertEqual((out["title"], out["style"], out["scene_count"]), ("How a Hash Map Works", "3d", 2))
            self.assertEqual(json.loads((ep / "script.json").read_text())["style"], "3d")
            self.assertEqual(w.validate(ctx, out), [])

    def test_isometric_pastel_is_ticked_alone_and_tells_the_writer_to_use_the_kit(self):
        from postcrew import factory_styles as fs
        with TempWorkspace() as ws:
            self.assertEqual(fs.save(ws, ["iso"]), ["iso"])
            self.assertTrue(fs.is_iso(fs.ticked(ws))); self.assertFalse(fs.is_3d(fs.ticked(ws)))
            for mix in (["signal", "iso"], ["iso", "3d"]):
                with self.assertRaises(ValueError):
                    fs.save(ws, mix)
            line = fs.instruction(["iso"])
            self.assertIn("styles/iso-pastel/STYLE.md", line); self.assertIn("explainer.js", line); self.assertIn("--check", line)

    def test_the_script_writer_writes_the_isometric_animation_and_checks_its_storyboard(self):
        from postcrew import factory_styles as fs
        with TempWorkspace() as ws, tempfile.TemporaryDirectory() as d:
            fs.save(ws, ["iso"])
            root = Path(d); kit = root / "styles" / "iso-pastel"; kit.mkdir(parents=True); (kit / "STYLE.md").write_text("# iso rules")
            ep = root / "episodes" / "e1"
            def fake_claude(ctx, prompt, tools, cwd, add_dirs=()):
                self.assertIn("=== STYLE.md (styles/iso-pastel) ===", prompt); self.assertIn("1080x1920", prompt)
                self.assertTrue(any("make-iso.mjs . --check" in t for t in tools)); self.assertEqual(Path(cwd), ep)
                (ep / "script.json").write_text(json.dumps({"style": "iso", "hook_options": ["One", "Two", "Three"], "beats": [{"say": "One app, one database. Why does it crash?"}, {"say": "One app, one database. " * 20}, {"say": "Then it slows down. " * 20}]}))
                (ep / "explainer.js").write_text("function explainer(ctx, W, H_, t) {}\nfunction scoreSound(k) {}")
                (ep / "youtube.json").write_text(json.dumps({"title": "Database Scaling", "description": "d", "tags": ["db"]}))
                return {}
            ctx = mock.Mock(ws=ws, cfg={}, cat={"label": "Short", "brief": "b", "format": "short"}, video={"format": "short"})
            w = shorts.ShortsWriter()
            with mock.patch.object(w, "_claude", side_effect=fake_claude), mock.patch("postcrew.agents.shorts.skill_version", return_value={}), \
                 mock.patch("postcrew.agents.shorts.iso_check", return_value=[]):
                out = w._plan_iso(ctx, root, ep, "e1", "Database Scaling", {"angle": "one to many"})
            self.assertEqual((out["title"], out["style"], out["scene_count"], out["words"]), ("Database Scaling", "iso", 3, 168))
            self.assertEqual(w.validate(ctx, out), [])

    def test_signal_alone_is_written_for_the_tech_glow_engine(self):
        from postcrew import factory_styles as fs
        with TempWorkspace() as ws, tempfile.TemporaryDirectory() as d:
            fs.save(ws, ["signal"])
            self.assertIn("tech-glow/STYLE.md", fs.instruction(["signal"]))
            root = Path(d); (root / "package.json").write_text("{}")
            for k in ("tech-glow", "iso-pastel"):
                (root / "styles" / k).mkdir(parents=True); (root / "styles" / k / "STYLE.md").write_text(f"# {k}")
            ep = root / "episodes" / "e1"
            def fake_claude(ctx, prompt, tools, cwd, add_dirs=()):
                self.assertIn("Tech Glow", prompt); self.assertIn("=== STYLE.md (styles/tech-glow) ===", prompt)
                self.assertIn("examples/binary-search", prompt); self.assertIn("glow3d.js", prompt)   # the published Short + 3D objects (2026-11-17)
                ep.mkdir(parents=True, exist_ok=True)
                (ep / "script.json").write_text(json.dumps({"style": "blue", "hook_options": ["One", "Two", "Three"], "beats": [{"say": "Find one number in a million?"}, {"say": "Binary search halves the range. " * 32}]}))
                (ep / "explainer.js").write_text("function explainer(){}\nfunction scoreSound(k){}")
                (ep / "youtube.json").write_text(json.dumps({"title": "Binary Search", "description": "d", "tags": []}))
                return {}
            ctx = mock.Mock(ws=ws, cfg={}, cat={"label": "Short", "brief": "b", "format": "short"}, video={"format": "short"})
            w = shorts.ShortsWriter()
            with mock.patch.object(w, "_claude", side_effect=fake_claude), mock.patch("postcrew.agents.shorts.skill_version", return_value={}), \
                 mock.patch("postcrew.agents.shorts.iso_check", return_value=[]):
                out = w._plan_iso(ctx, root, ep, "e1", "Binary Search", {}, look="blue")
            self.assertEqual((out["look"], out["ticked"]), ("blue", ["signal"]))
            self.assertEqual(w.validate(ctx, out), [])

    def test_an_isometric_storyboard_with_problems_or_too_many_words_goes_back(self):
        out = {"title": "t", "scene_count": 8, "style": "iso", "long": False, "words": 170, "word_budget": 140,
               "storyboard_errors": ["beat 3: text \"cache\" is 22 px"]}
        p = shorts.ShortsWriter().validate(mock.Mock(), out)
        self.assertTrue(any("22 px" in x for x in p)); self.assertTrue(any("170 words" in x for x in p))

    def test_a_3d_storyboard_that_does_not_compile_or_is_too_long_goes_back(self):
        out = {"title": "t", "scene_count": 3, "style": "3d", "long": False, "words": 200, "word_budget": 125,
               "storyboard_errors": ["beat 2: anchor \"@heap\" is not a word of say"]}
        p = shorts.ShortsWriter().validate(mock.Mock(), out)
        self.assertTrue(any("@heap" in x for x in p)); self.assertTrue(any("200 words" in x for x in p))


class HookTests(unittest.TestCase):
    """Owner, 2026-11-17: every script opens with a catch line (retention is bad)."""

    def test_a_good_catch_line_passes(self):
        s = {"beats": [{"say": "You hit Back and the last page comes right back. How does your browser remember?"}], "hook_options": ["a", "b", "c"]}
        self.assertEqual(shorts.hook_problems(s), [])

    def test_a_lecture_opener_a_long_hook_or_no_options_is_sent_back(self):
        self.assertTrue(shorts.hook_problems({"beats": [{"say": "In this video we learn linked lists."}], "hook_options": ["a", "b", "c"]}))
        self.assertTrue(shorts.hook_problems({"beats": [{"say": " ".join(["word"] * 30)}], "hook_options": ["a", "b", "c"]}))
        self.assertTrue(shorts.hook_problems({"beats": [{"say": "You hit Back. How?"}]}))

    def test_every_look_gets_the_opening_rule(self):
        self.assertIn("CATCH LINE", shorts.HOOK_RULE)
