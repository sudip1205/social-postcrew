"""Motion Studio: the reference library, the house style, feedback, the Creative Director and the Quality Director."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from postcrew import llm as llm_mod
from postcrew.agents import quality as q
from postcrew.agents.base import AgentError
from postcrew.agents.direction import CreativeDirectorAgent, plan_problems
from postcrew.motion import analyze as an
from postcrew.motion import frames as fr
from postcrew.motion import library as lib
from postcrew.motion.cli import check

from helpers import ScriptedLLM, TempWorkspace

FFMPEG = bool(shutil.which("ffmpeg"))


def three_scenes(path):
    """A 12-second 540x960 video: 3s empty, 3s with a picture that builds, 6s of the same still picture."""
    box = "drawbox=x=90:y=200:w=360:h=360:color=white@1:t=fill"
    vf = (f"drawbox=x=90:y=200:w=360:h=360:color=white@1:t=fill:enable='gte(t,3)',"
          f"drawbox=x=90:y=600:w=360:h=80:color=0x24c1ff@1:t=fill:enable='between(t,4.5,6)',"
          f"drawbox=x=60:y=150:w=420:h=520:color=0x7c3aed@1:t=fill:enable='gte(t,6)'")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x0d0d0d:s=540x960:d=12:r=10",
                    "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return box


ANALYSIS = {"summary": "fast, bold", "scenes": [{"shot": 1, "purpose": "hook", "picture": "a big number", "on_screen_text": "3 words, huge",
                                                  "motion": "counts up", "transition_in": "cut", "energy": "high"}],
            "profile": {"profile_name": "Bold minimal", "visual_system": {"background": "dark", "palette": ["#111111"], "typography": "bold sans",
                                                                          "composition": "centred, full height"},
                        "motion_language": {"preferred": ["pop"], "transitions": ["zoom"], "motion_intensity": "high"},
                        "storytelling": {"hook_type": "question", "scene_rhythm": "fast", "ending": "takeaway"},
                        "constraints": {"avoid": ["clutter"]}},
            "patterns": [{"name": "number reveal", "purpose": "hook", "recipe": "a big number counts up, a label explains it"}],
            "strengths": ["big type"], "weaknesses": ["a slow middle"]}


TRANSCRIPT = ("Most people get this wrong. They think a cache makes every read fast. Watch what happens when the cache is cold. "
              "The first request goes all the way to the database, and that takes two hundred milliseconds. The second one is instant. "
              "So the trick is not the cache, it is what you keep in it. Here is the rule I use.")
SCRIPT = {"summary": "contrarian hook, one example", "structure": [{"part": "hook", "purpose": "hook", "share": 10, "technique": "the wrong belief"}],
          "devices": ["contrast"], "profile": {"hook_type": "the wrong answer first", "structure": "hook > example > rule", "tone": "direct",
                                               "sentence_style": "short", "pacing": "brisk", "ending": "one rule", "rules": ["one idea per sentence"]},
          "patterns": [{"name": "myth then truth", "purpose": "hook", "recipe": "state the common belief, then show it failing"}],
          "strengths": ["clear"], "weaknesses": ["no recap"]}


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class FrameTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="motion-"))
        self.video = self.dir / "v.mp4"
        three_scenes(self.video)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_probe_cuts_and_measure(self):
        info = fr.probe(self.video)
        self.assertEqual((info["width"], info["height"]), (540, 960))
        self.assertAlmostEqual(info["seconds"], 12, delta=0.3)
        cuts = fr.detect_cuts(self.video)
        self.assertTrue(any(abs(c - 3) < 0.3 for c in cuts), cuts)
        empty = fr.measure(fr.grab(self.video, 1.0, self.dir / "a.png"))
        full = fr.measure(fr.grab(self.video, 8.0, self.dir / "b.png"))
        self.assertLess(empty["fill"], q.EMPTY_FILL)
        self.assertGreater(full["fill"], 0.2)
        self.assertGreater(full["height"], 0.5)
        self.assertEqual(fr.change(self.dir / "b.png", fr.grab(self.video, 11.0, self.dir / "c.png")), 0.0)

    def test_the_quality_director_finds_an_empty_and_a_still_scene(self):
        ctx = SimpleNamespace(run=SimpleNamespace(dir=self.dir))
        media = {"path": str(self.video), "scene_seconds": [3, 3, 6], "seconds": 12}
        scenes = [{"narration": "a"}, {"narration": "b"}, {"narration": "c"}]
        measures, sheets = q.QualityDirectorAgent().look(ctx, media, scenes)
        self.assertEqual(len(measures), 3)
        self.assertTrue(all(Path(s).exists() for s in sheets))
        found = {(f["scene"], f["kind"]) for f in q.picture_findings(measures, still_s=3.0)}
        self.assertIn((1, "empty"), found)
        self.assertIn((3, "still"), found)
        self.assertNotIn((2, "empty"), found)

    def test_motion_check_of_a_file_runs_without_ai(self):
        with TempWorkspace() as ws:
            out = []
            code = check(ws, str(self.video), ai=False, log=out.append)
            self.assertIn("picture quality", out[-1])
            self.assertIn(code, (0, 1))


class LlmImageTests(unittest.TestCase):
    def test_claude_code_reads_the_images_itself(self):
        seen = {}

        def runner(cmd, input, **kw):
            seen.update(cmd=cmd, prompt=input)
            return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
                {"subtype": "success", "structured_output": {"ok": True}, "total_cost_usd": 0.01}))
        cc = llm_mod.ClaudeCode({"llm": {"backend": "claude-code", "claude_path": "/bin/sh"}}, runner=runner)
        cc.call("quality", "sys", "look", {"type": "object"}, images=["/tmp/sheet-1.png"])
        tools = seen["cmd"][seen["cmd"].index("--tools") + 1]
        self.assertIn("Read", tools)
        self.assertIn("/tmp/sheet-1.png", seen["prompt"])

    def test_the_claude_api_gets_the_images_inline(self):
        tmp = Path(tempfile.mkdtemp())
        img = tmp / "s.png"
        from PIL import Image
        Image.new("RGB", (4, 4), "red").save(img)
        sent = {}

        class Resp:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(self.body).encode()

        def opener(req, timeout=None):
            sent.update(json.loads(req.data))
            return Resp({"content": [{"type": "tool_use", "name": "respond", "input": {"ok": True}}], "usage": {}})
        cfg = {"llm": {"backend": "anthropic", "api": {}, "defaults": {}, "agents": {}}}
        api = llm_mod.Anthropic(cfg, {"anthropic_api_key": "k"}, opener=opener)
        api.call("quality", "sys", "look", {"type": "object"}, images=[str(img)])
        content = sent["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(content[-1]["type"], "text")
        api.call("quality", "sys", "again", {"type": "object"})   # a later call without images sends none
        self.assertEqual([c["type"] for c in sent["messages"][0]["content"]], ["text"])
        shutil.rmtree(tmp, ignore_errors=True)


class LibraryTests(unittest.TestCase):
    def test_a_reference_needs_rights_and_a_real_video_file(self):
        with TempWorkspace() as ws:
            L = lib.Library(ws)
            with self.assertRaises(ValueError):
                L.add("/nonexistent.mp4", "found-it-online")
            with self.assertRaises(ValueError):
                L.add("/nonexistent.mp4", "own")   # Postcrew never downloads: it must be a file
            self.assertEqual(L.references(), [])

    def test_the_house_style_starts_built_in_and_keeps_versions(self):
        with TempWorkspace() as ws:
            L = lib.Library(ws)
            self.assertEqual(L.house()["source"], "built-in")
            v1 = L.save_house(dict(lib.DEFAULT_HOUSE, profile_name="One"))
            v2 = L.save_house(dict(lib.DEFAULT_HOUSE, profile_name="Two"))
            self.assertEqual((v1["version"], v2["version"]), (1, 2))
            self.assertEqual(L.house()["profile_name"], "Two")
            self.assertEqual(L.use_version(1)["profile_name"], "One")
            self.assertEqual(L.reset_house()["source"], "built-in")

    def test_only_approved_feedback_becomes_a_preference(self):
        with TempWorkspace() as ws:
            L = lib.Library(ws)
            f = L.add_feedback("2026-11-03-110927", rating=2, kind="text_too_small", scene=7)
            self.assertEqual(L.preferences(), [])
            self.assertNotIn("APPROVED PREFERENCES", L.brief())
            L.approve_feedback(f["id"])
            self.assertIn(lib.KIND_RULE["text_too_small"], L.brief())
            g = L.add_feedback("x", kind="other", comment="more contrast on code")
            L.approve_feedback(g["id"], rule="Code text is bright on a dark card.")
            self.assertEqual(len(L.preferences()), 2)
            L.forget_preference(1)
            self.assertEqual([p["rule"] for p in L.preferences()], ["Code text is bright on a dark card."])
            with self.assertRaises(ValueError):
                L.add_feedback("x", kind="nonsense")

    def test_patterns_fit_the_scene_purpose(self):
        with TempWorkspace() as ws:
            pats = lib.Library(ws).relevant_patterns("reveal", "the wrong path fails")
            self.assertEqual(pats[0]["name"], "wrong then right")


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class AnalyzeTests(unittest.TestCase):
    def test_analyse_approve_and_build_the_house_style(self):
        tmp = Path(tempfile.mkdtemp())
        video = tmp / "ref.mp4"
        three_scenes(video)
        with TempWorkspace() as ws:
            L = lib.Library(ws)
            meta = L.add(video, "own", title="My best short")
            llm = ScriptedLLM({"motion": [ANALYSIS]})
            with mock.patch.object(lib, "transcribe", return_value=None):
                meta, a = an.analyze(ws, meta["id"], llm=llm, log=lambda m: None)
            self.assertEqual(meta["status"], "profile_review")
            self.assertEqual(meta["analyzed"], ["screen"])
            self.assertTrue(llm.images and all(Path(p).exists() for p in llm.images))   # the model saw the contact sheets
            self.assertGreater(a["screen"]["measured"]["shots"], 1)
            with self.assertRaises(ValueError):
                an.build_house(ws, llm=llm, log=lambda m: None)   # nothing approved yet
            # the script too, from a pasted transcript: no images, its own result next to the screens'
            sllm = ScriptedLLM({"motion": [SCRIPT]})
            meta, a = an.process(ws, meta["id"], ["script"], transcript=TRANSCRIPT, llm=sllm, log=lambda m: None)
            self.assertEqual(meta["analyzed"], ["screen", "script"])
            self.assertEqual(meta["transcript_source"], "pasted")
            self.assertFalse(sllm.images)
            self.assertIn("screen", a)
            self.assertEqual(a["script"]["measured"]["words"], len(TRANSCRIPT.split()))
            L.set_status(meta["id"], "ready")
            house = {"profile": ANALYSIS["profile"], "patterns": ANALYSIS["patterns"], "script": SCRIPT["profile"],
                     "script_patterns": SCRIPT["patterns"], "why": "shared bold look"}
            style = an.build_house(ws, llm=ScriptedLLM({"motion": [house]}), log=lambda m: None)
            self.assertEqual(style["script"]["hook_type"], "the wrong answer first")
            self.assertIn("the wrong answer first", L.script_brief())
            self.assertEqual(style["version"], 1)
            self.assertIn("small unreadable text", style["constraints"]["avoid"])   # the quality floor stays
            self.assertIn("clutter", style["constraints"]["avoid"])
            self.assertTrue(1.8 <= style["pacing"]["shot_seconds"] <= 5.0)          # measured, kept in range
            self.assertEqual(L.house()["profile_name"], "Bold minimal")
            self.assertTrue(any(p["source"] == meta["id"] for p in L.patterns()))
        shutil.rmtree(tmp, ignore_errors=True)


class ScriptAndUrlTests(unittest.TestCase):
    def test_a_url_reference_is_fetched_for_what_was_asked_only(self):
        from postcrew.motion import fetch as fetch_mod
        with TempWorkspace() as ws:
            L = lib.Library(ws)
            with self.assertRaises(ValueError):
                L.add_url("not a url", "own")
            with self.assertRaises(ValueError):
                L.add_url("https://example.com/v", "it-is-public")
            meta = L.add_url("https://example.com/shorts/abc", "own")
            calls = []

            def fake_fetch(url, dest, video=True, subs=True, log=print):
                calls.append((video, subs))
                return {"title": "Cache myths", "creator": "Me", "seconds": 40, "video": None, "transcript": TRANSCRIPT}
            with mock.patch.object(fetch_mod, "fetch", side_effect=fake_fetch):
                meta, a = an.process(ws, meta["id"], ["script"], llm=ScriptedLLM({"motion": [SCRIPT]}), log=lambda m: None)
            self.assertEqual(calls, [(False, True)])          # script only: subtitles, no video
            self.assertEqual(meta["title"], "Cache myths")
            self.assertEqual(meta["transcript_source"], "subtitles")
            self.assertEqual(meta["status"], "profile_review")

    def test_a_script_analysis_without_words_fails_with_the_reason(self):
        with TempWorkspace() as ws:
            L = lib.Library(ws)
            meta = L.add_url("https://example.com/v", "own")
            with mock.patch("postcrew.motion.fetch.fetch", return_value={"title": "", "creator": "", "seconds": 30, "video": None, "transcript": ""}):
                with self.assertRaises(an.AnalyzeError):
                    an.process(ws, meta["id"], ["script"], llm=ScriptedLLM({}), log=lambda m: None)
            self.assertEqual(L.meta(meta["id"])["status"], "failed")
            self.assertIn("transcript", L.meta(meta["id"])["status_reason"])

    def test_subtitles_become_plain_text_without_the_scrolling_repeats(self):
        from postcrew.motion.fetch import vtt_text
        vtt = ("WEBVTT\nKind: captions\nLanguage: en\n\n00:00:00.000 --> 00:00:02.000\nmost people get\n\n"
               "00:00:02.000 --> 00:00:04.000\nmost people get\nthis <c>wrong</c>\n\n00:00:04.000 --> 00:00:05.000\nthis wrong\n")
        self.assertEqual(vtt_text(vtt), "most people get this wrong")

    def test_the_script_writer_gets_the_learned_style(self):
        from postcrew.agents.script import ScriptWriter
        with TempWorkspace() as ws:
            ctx = fake_ctx(ws, {"scenes": []}, None)
            text = ScriptWriter().prompt(ctx, "writer")
            self.assertNotIn("{{script_style}}", text)
            self.assertNotIn("SCRIPT STYLE", text)          # nothing learned yet: the writer's own rules
            L = lib.Library(ws)
            L.save_house(dict(lib.DEFAULT_HOUSE, script=dict(SCRIPT["profile"], patterns=SCRIPT["patterns"])))
            text = ScriptWriter().prompt(ctx, "writer")
            self.assertIn("SCRIPT STYLE", text)
            self.assertIn("myth then truth", text)


class TranscribeTests(unittest.TestCase):
    def test_a_gpu_without_cuda_falls_back_to_the_cpu(self):
        import sys
        devices = []

        class Model:
            def __init__(self, name, device, compute_type):
                devices.append(device)
                if device == "auto":
                    raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")

            def transcribe(self, path, vad_filter):
                return [SimpleNamespace(start=0.0, end=1.0, text=" hello there ")], None
        with mock.patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=Model)}):
            out = lib.transcribe("v.mp4", log=lambda m: None)
        self.assertEqual(devices, ["auto", "cpu"])
        self.assertEqual((out["text"], out["words"]), ("hello there", 2))


class ShortLengthTests(unittest.TestCase):
    def test_a_short_is_limited_by_how_fast_a_video_really_goes(self):
        from postcrew.checks import script_problems, short_max_words
        from postcrew.platforms import SPOKEN_WPS
        self.assertEqual(short_max_words(), int(175 * SPOKEN_WPS))
        self.assertGreater(short_max_words(), 400)   # the lab's slow-pace Shorts run 2.9-3.5 words a second: 400 words is about 2 minutes

        def length_problems(words):
            script = {"text": " ".join(["word"] * words), "scenes": []}
            return [p for p in script_problems(script, {"format": "short", "wps": 2.0}, {}, {}) if "Short holds" in p]
        self.assertEqual(length_problems(360), [])            # was refused as "190 seconds" at the slow pace
        msg = length_problems(short_max_words() + 20)
        self.assertTrue(msg and "Cut at least 20 words" in msg[0])

    def test_the_editor_is_told_the_word_room_of_a_short(self):
        from postcrew.agents.base import length_note
        from postcrew.checks import short_max_words
        ctx = SimpleNamespace(video={"format": "short"}, outputs={"writer": {"text": "w " * (short_max_words() - 10)}})
        note = length_note(ctx)
        self.assertIn("only 10 words of room", note)
        self.assertIn("which sentence to cut", note)
        ctx.outputs["writer"]["text"] = "w " * 100
        self.assertIn("may add words", length_note(ctx))
        self.assertEqual(length_note(SimpleNamespace(video={"format": "long"}, outputs={})), "")


class StudioApiTests(unittest.TestCase):
    def test_upload_analyse_approve_through_the_api(self):
        import io
        from postcrew.studio.motion_api import MotionAPI
        tmp = Path(tempfile.mkdtemp())
        with TempWorkspace() as ws:
            api = MotionAPI(ws)
            with self.assertRaises(ValueError):
                api.upload({"name": "a.mp4", "rights": ""}, io.BytesIO(b"x"), 1)     # no rights declared
            with self.assertRaises(ValueError):
                api.upload({"name": "a.exe", "rights": "own"}, io.BytesIO(b"x"), 1)  # not a video
            if FFMPEG:
                three_scenes(tmp / "v.mp4")
                data = (tmp / "v.mp4").read_bytes()
                rid = api.upload({"name": "v.mp4", "rights": "own", "title": "Mine"}, io.BytesIO(data), len(data))["reference"]["id"]
                self.assertFalse(list((Path(ws.root) / "motion" / "incoming").iterdir()))   # the upload was moved in
                with mock.patch("postcrew.motion.analyze.process") as proc:
                    api.analyze(rid, {"modes": ["script"], "transcript": "words"})
                    api.worker.join(10)
                proc.assert_called_once()
                self.assertEqual(proc.call_args[0][2], ["script"])
                with self.assertRaises(ValueError):
                    api.analyze(rid, {"modes": []})
                with self.assertRaises(ValueError):
                    api.action(rid, "approve")        # nothing analysed yet
                lib.Library(ws).update(rid, analyzed=["script"], status="profile_review")
                st = api.action(rid, "approve")
                self.assertEqual(st["references"][0]["status"], "ready")
                api.action(rid, "delete")
                self.assertEqual(api.state()["references"], [])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_a_restart_marks_half_done_analyses_failed(self):
        from postcrew.studio.motion_api import MotionAPI
        with TempWorkspace() as ws:
            L = lib.Library(ws)
            rid = L.add_url("https://example.com/v", "own")["id"]
            L.set_status(rid, "downloading")
            MotionAPI(ws)
            self.assertEqual(L.meta(rid)["status"], "failed")
            self.assertIn("restarted", L.meta(rid)["status_reason"])


class DirectorTests(unittest.TestCase):
    def test_plan_problems_a_program_can_see(self):
        long = "word " * 40
        scenes = [{"layout": "title", "narration": "hi"}] + [{"layout": "points", "narration": long, "items": ["a"]} for _ in range(3)] \
            + [{"layout": "diagram", "narration": "x"}, {"layout": "statement", "part": "closing", "narration": "bye"}]
        msgs = " | ".join(m for _n, m in plan_problems(scenes, lib.DEFAULT_HOUSE))
        self.assertIn("hook is a title card", msgs)
        self.assertIn("third points scene in a row", msgs)
        self.assertIn("words only", msgs)
        self.assertIn("words-only picture", msgs)

    def test_notes_travel_with_the_scenes_and_a_model_failure_does_not_stop_the_run(self):
        with TempWorkspace() as ws:
            script = {"scenes": [{"layout": "points", "narration": "one two", "part": "idea"},
                                 {"layout": "statement", "narration": "bye", "part": "closing"}]}
            note = {"scene": 1, "purpose": "explanation", "visual": "a cache in front of a database", "focus": "the cache",
                    "beats": ["db", "cache"], "layout": "diagram", "pattern": ""}
            ctx = fake_ctx(ws, script, ScriptedLLM({"direction": [{"concept": "one diagram grows", "scenes": [note], "risks": []}]}))
            out = CreativeDirectorAgent().run(ctx, [])
            self.assertEqual(out["notes"], 1)
            self.assertEqual(ctx.outputs["writer"]["scenes"][0]["direction"]["visual"], "a cache in front of a database")
            self.assertNotIn("direction", ctx.outputs["writer"]["scenes"][1])   # the closing card is not directed
            ctx = fake_ctx(ws, script, ScriptedLLM({}))
            out = CreativeDirectorAgent().run(ctx, [])
            self.assertIn("skipped", out)


def fake_ctx(ws, script, llm, media=None, motion=None):
    events = []
    run = SimpleNamespace(dir=Path(ws.root) / "runs" / "t", event=lambda *a, **k: events.append(a), add_cost=lambda *a: None,
                          add_tokens=lambda *a: None)
    run.dir.mkdir(parents=True, exist_ok=True)
    cfg = {"video": {"motion": motion or {}}, "profile": {"name": "Sam"}, "categories": {"c": {"label": "C"}}}
    return SimpleNamespace(ws=ws, cfg=cfg, outputs={"writer": script, "media": media or {}}, run=run, llm=llm, flags={},
                           platform="youtube", profile={"name": "Sam"}, events=events, category="c", cat={"label": "C"},
                           video={"format": "short"})


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class QualityDirectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.video = self.tmp / "v.mp4"
        three_scenes(self.video)
        self.script = {"scenes": [{"layout": "diagram", "narration": "a b c"}, {"layout": "points", "narration": "d e f"},
                                  {"layout": "statement", "narration": "g h", "part": "closing"}]}
        self.media = {"path": str(self.video), "scene_seconds": [3, 3, 6], "seconds": 12, "source": "crew"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def verdict(self, overall, scenes=()):
        return {"scores": {c: overall for c in q.CRITERIA}, "overall": overall, "summary": "s", "scenes": list(scenes)}

    def test_a_good_video_passes(self):
        with TempWorkspace() as ws:
            ctx = fake_ctx(ws, self.script, ScriptedLLM({"quality": [self.verdict(90)]}), self.media, {"hold_below": 0})
            ctx.outputs["media"]["scene_seconds"] = [3, 3, 6]
            with mock.patch.object(q, "picture_findings", return_value=[]):
                out = q.QualityDirectorAgent().run(ctx, [])
            self.assertEqual((out["score"], out["held"], out["redrawn"]), (90, False, []))
            self.assertEqual(q.QualityDirectorAgent().validate(ctx, out), [])
            self.assertTrue(ctx.llm.images)   # the vision model got the sheets

    def test_an_empty_scene_is_redrawn_once_then_held(self):
        fix = {"scene": 1, "severity": "error", "problem": "empty", "redraw": True, "layout": "diagram", "nodes": ["A", "B"]}
        with TempWorkspace() as ws:
            ctx = fake_ctx(ws, self.script, ScriptedLLM({"quality": [self.verdict(80, [fix])]}), self.media)
            with mock.patch("postcrew.agents.graphics.GraphicsAgent._apply", return_value=[1]):
                out = q.QualityDirectorAgent().run(ctx, [])
                self.assertEqual(out["score"], 59)          # an empty scene caps the score
                self.assertEqual(out["redrawn"], [1])
                self.assertTrue(q.QualityDirectorAgent().validate(ctx, out))   # a send-back: draw it again
                out2 = q.QualityDirectorAgent().run(ctx, [])                   # the second look: no more redraws
            self.assertEqual(out2["redrawn"], [])
            self.assertTrue(out2["held"])
            self.assertEqual(q.QualityDirectorAgent().validate(ctx, out2), [])

    def test_without_a_vision_model_it_judges_on_the_measurements(self):
        with TempWorkspace() as ws:
            ctx = fake_ctx(ws, self.script, ScriptedLLM({}), self.media, {"max_redraws": 0})
            out = q.QualityDirectorAgent().run(ctx, [])
            self.assertFalse(out["vision"])
            self.assertLessEqual(out["score"], 59)
            self.assertTrue(out["held"])

    def test_the_supervisor_draws_again_from_the_frame_steps(self):
        from postcrew.agents.supervisor import Supervisor, crew_for
        crew = crew_for("youtube")
        sup = Supervisor(crew)
        d = sup._diagnose(SimpleNamespace(), "quality", ["picture quality 50/100"], {}, {})
        self.assertEqual((d["action"], d["target"]), ("rewind", "media"))
        self.assertLess(sup.order.index("direction"), sup.order.index("graphics"))
        self.assertLess(sup.order.index("hooks"), sup.order.index("quality"))


if __name__ == "__main__":
    unittest.main()
