"""Factory > Voice (owner, 2026-11-16): scripts written ahead, the owner's voice cleaned and matched to dip_puck, and two approvals
before a video is made."""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from helpers import TempWorkspace  # noqa: E402
from test_shorts import DAY, fake_factory  # noqa: E402

from postcrew import voice_clean, voice_desk  # noqa: E402
from postcrew.crew import run_crew  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg"))


def said(text, start=0.0, per=0.3, gap=0.05):
    """Fake Whisper words for `text`, one every `per` seconds from `start`."""
    out, t = [], start
    for w in text.split():
        out.append({"w": w, "s": round(t, 3), "e": round(t + per - gap, 3)})
        t += per
    return out


class CleaningTests(unittest.TestCase):
    """Patterns from the owner's real take (2026-11-17, the linked-list Short)."""

    def keep(self, words, texts):
        out, removed = voice_clean.clean(words, texts)
        return [o.get("said") for o in out], removed, out

    def test_numbers_and_ordinals_match_their_words(self):
        self.assertEqual(voice_desk.tokens("Index forty-five holds 45."), ["index", "forty", "five", "holds", "forty", "five"])
        self.assertEqual([t for t, _ in voice_clean.tokens("3rd type")], ["third", "type"])

    def test_a_restarted_sentence_keeps_only_the_last_take(self):
        words = said("A single linked list, a single linked list is a chain of nodes.")
        kept, removed, _ = self.keep(words, ["A singly linked list is a chain of nodes."])
        self.assertEqual(kept, ["a single linked list is a chain of nodes."])
        self.assertEqual(removed, ["A single linked list,"])

    def test_a_retake_after_a_mispronounced_word_wins(self):
        words = said("Delete is a big win. With the node in hand, its neighbors lived around it. "
                     "Delete is a big win. With the node in hand, its neighbors link around it.")
        kept, removed, out = self.keep(words, ["Delete is the big win. With the node in hand, its neighbors link around it."])
        self.assertTrue(kept[-1].endswith("neighbors link around it."))
        self.assertTrue(any("lived" in r for r in removed))
        self.assertEqual([o["bad"] for o in out], [[], []])

    def test_stutters_fillers_and_a_false_start_are_cut(self):
        words = said("Walk forward from, um, walk forward from A, fine. But from from C, there is no way back.")
        kept, removed, _ = self.keep(words, ["Walk forward from A, fine. But from C, there is no way back."])
        self.assertEqual(kept, ["walk forward from A, fine.", "But from C, there is no way back."])

    def test_a_mispronounced_word_never_said_again_is_marked_for_dip_puck(self):
        words = said("The fix: a second pointer on every node, prev. That makes it a double latest.")
        _, _, out = self.keep(words, ["The fix: a second pointer on every node, prev. That makes it a doubly linked list."])
        self.assertEqual(out[0]["bad"], [])
        self.assertTrue(out[1]["bad"])                       # "latest" for "linked list"

    def test_the_american_version_reads_the_script_with_your_abbreviations(self):
        words = said("The fix: a second pointer on every node, previous. That makes it a doubly linked list.")
        _, _, out = self.keep(words, ["The fix: a second pointer on every node, prev. That makes it a doubly linked list."])
        self.assertEqual(out[0]["spoken"], "The fix: a second pointer on every node, previous.")
        self.assertEqual(out[1]["spoken"], "That makes it a doubly linked list.")

    def test_own_wording_of_small_words_is_not_a_mistake(self):
        words = said("Delete is a big win.")
        _, _, out = self.keep(words, ["Delete is the big win."])
        self.assertEqual(out[0]["bad"], [])

    def test_the_second_pass_finds_repeats_whisper_missed_in_the_long_take(self):
        ws_ = said("single must single must first walk from the head to find to find who points at it")
        cuts = voice_desk.repeats(ws_)
        self.assertEqual(len(cuts), 2)
        self.assertEqual(cuts[0], (ws_[0]["s"], ws_[2]["s"]))                      # the first "single must"
        ws_ = said("if this was helpful if this was useful please like")
        self.assertEqual(voice_desk.repeats(ws_), [(ws_[0]["s"], ws_[4]["s"])])   # a restart that changed its last word

    def test_a_line_that_was_not_recorded_is_reported_missing(self):
        _, _, out = self.keep(said("Line one is here."), ["Line one is here.", "Completely different words now."])
        self.assertTrue(out[1]["missing"])


@mock.patch("postcrew.agents.credentials.check_claude", new=lambda *a, **k: {"state": "ok", "message": "Claude Code is ready"})
class DeskRunTests(unittest.TestCase):
    def test_a_run_writes_the_script_then_waits_for_the_approvals(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            res = run_crew(ws, DAY, "short-tip", platform="youtube")
            self.assertFalse(res["ok"])
            self.assertTrue(res["waiting"])
            self.assertIn("approve the script", res["reason"])
            self.assertFalse(any(c[0][:3] == ["npm", "run", "make"] for c in calls))   # nothing rendered
            self.assertEqual(ws.queue(), [])
            status = json.loads((ws.runs_dir / res["run_id"] / "status.json").read_text())
            self.assertEqual(status["state"], "waiting")
            self.assertEqual(status["steps"]["media"]["state"], "waiting")
            slug = voice_desk.index(ws)["days"][DAY.isoformat()]
            self.assertEqual(voice_desk.desk(root / "episodes" / slug)["run"]["state"], "waiting")

    def test_with_both_approved_the_next_run_reuses_the_script_and_makes_the_video(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, calls):
            run_crew(ws, DAY, "short-tip", platform="youtube")
            slug = voice_desk.index(ws)["days"][DAY.isoformat()]
            with mock.patch.object(voice_desk, "_start"):   # the run started on approval is run below, in the foreground
                voice_desk.approve_script(ws, slug)
                _fake_generate(ws, slug, "am_puck")
                ep = voice_desk.choose(ws, slug, "am_puck")
            self.assertEqual(ep["voice"]["state"], "approved")
            self.assertEqual([json.loads((root / "episodes" / slug / "script.json").read_text())[k] for k in ("voice", "voice_kokoro")], ["own", "am_puck"])
            n_claude = sum(1 for c in calls if "claude" in c[0][0])
            res = run_crew(ws, DAY, "short-tip", platform="youtube")
            self.assertTrue(res["ok"], res)
            self.assertEqual(sum(1 for c in calls if "claude" in c[0][0]), n_claude)   # the script was not written again
            self.assertTrue(any(c[0][:3] == ["npm", "run", "make"] for c in calls))
            self.assertEqual(len(ws.queue()), 1)

    def test_approving_never_makes_the_video_by_itself(self):
        """Owner, 2026-11-17: the video is made only when you press Make the video."""
        with TempWorkspace() as ws, fake_factory(ws, desk=True):
            run_crew(ws, DAY, "short-tip", platform="youtube")
            slug = voice_desk.index(ws)["days"][DAY.isoformat()]
            started = []
            with mock.patch.object(voice_desk, "_start", side_effect=lambda s, what, fn: started.append((s, what))):
                voice_desk.approve_script(ws, slug)
                _fake_generate(ws, slug, "dip_puck")
                voice_desk.choose(ws, slug, "dip_puck")
                self.assertEqual(started, [])
                voice_desk.make(ws, slug)
            self.assertEqual(started, [(slug, "video")])

    def test_editing_a_line_needs_a_new_approval_and_a_new_recording(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (root, _):
            run_crew(ws, DAY, "short-tip", platform="youtube")
            slug = voice_desk.index(ws)["days"][DAY.isoformat()]
            ep_dir = root / "episodes" / slug
            d = voice_desk.desk(ep_dir)
            d.update(script="approved", voice={"state": "approved", "mode": "own"})
            voice_desk._save_desk(ep_dir, d)
            ep = voice_desk.episode(ws, slug)
            new = list(ep["lines"])
            new[0] = "A new first line."
            ep = voice_desk.save_lines(ws, slug, new)
            self.assertEqual(ep["script"], "draft")
            self.assertEqual(ep["voice"]["state"], "none")
            self.assertEqual(json.loads((ep_dir / "script.json").read_text())["scenes"][0]["text"], "A new first line.")

    def test_writing_again_with_notes_reaches_the_writer(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True) as (_, calls):
            run_crew(ws, DAY, "short-tip", platform="youtube")
            run_crew(ws, DAY, "short-tip", platform="youtube", options={"rewrite": True, "notes": ["make the hook about a bank queue"]})
            prompts = [c[1]["input"] for c in calls if "claude" in c[0][0]]
            self.assertEqual(len(prompts), 2)
            self.assertIn("make the hook about a bank queue", prompts[1])

    def test_the_desk_lists_your_plans_and_other_waiting_scripts(self):
        with TempWorkspace() as ws, fake_factory(ws, desk=True), mock.patch.object(voice_desk, "_has_whisper", return_value=True):
            run_crew(ws, DAY, "short-tip", platform="youtube")   # a manual run: no plan, so it shows under the other scripts
            v = voice_desk.view(ws)
            self.assertEqual(v["plans"], [])
            self.assertEqual(len(v["others"]), 1)
            slug = v["others"][0]["slug"]
            voice_desk.delete(ws, slug)                               # Delete: gone from the desk, kept in episodes/.deleted
            self.assertEqual(voice_desk.view(ws)["others"], [])
            self.assertNotIn(slug, (voice_desk.index(ws).get("days") or {}).values())
            self.assertEqual(len(list((voice_desk._root(ws) / "episodes" / ".deleted").iterdir())), 1)

@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg is needed")
class ProcessTests(unittest.TestCase):
    def test_a_recording_is_cleaned_converted_and_cut_into_lines(self):
        with TempWorkspace() as ws:
            root = ws.root / "shorts-factory"
            (root / "episodes").mkdir(parents=True)
            (root / "package.json").write_text("{}")
            cfg = ws.config()
            cfg["platforms"]["youtube"]["video"]["factory_path"] = str(root)
            ws.save_config(cfg)
            slug = "2026-11-03-binary"
            ep = root / "episodes" / slug
            ep.mkdir()
            lines = ["Start in the middle.", "Throw away the left half."]
            (ep / "script.json").write_text(json.dumps({"style": "iso", "beats": [{"say": t} for t in lines]}))
            voice_desk._save_desk(ep, {"day": DAY.isoformat(), "slug": slug, "script": "approved", "voice": {"state": "processing"}})
            (ep / "voice-take").mkdir()
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=6", "-ar", "48000", str(ep / "voice-take" / "upload.wav")], check=True)
            words = said("Start in the middle.", 0.2) + said("um", 1.6) + said("Throw away the left half.", 2.5)
            conv = lambda cfg, src, out: shutil.copy(src, out)   # Seed-VC stand-in: same length, same audio
            def speak(text, out):   # dip_puck stand-in: a short tone per sentence
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=1.2", "-ar", "48000", "-ac", "1", str(out)], check=True)
            voice_desk.process(ws, slug, converter=conv, words_of=lambda f: words, speaker=speak)
            rep = json.loads((ep / "voice-take" / "report.json").read_text())
            self.assertEqual(rep["kept_lines"], 2)
            self.assertEqual(rep["removed"], ["um"])
            self.assertFalse(rep["outro_recorded"])                 # the outro line is read by dip_puck
            self.assertEqual(voice_desk.desk(ep)["voice"]["state"], "ready")
            self.assertTrue((ep / "voice-take" / "scenes" / "scene1.wav").exists())
            self.assertTrue((ep / "voice-take" / "scenes-us" / "scene1.wav").exists())     # the American version too
            self.assertTrue((ep / "voice-take" / "take-american.wav").exists())
            with mock.patch.object(voice_desk, "_start"):
                voice_desk.choose(ws, slug, "own")
            self.assertTrue((ep / "voice" / "scene0.wav").exists())
            self.assertFalse((ep / "voice" / "scene2.wav").exists())
            s = json.loads((ep / "script.json").read_text())
            self.assertEqual((s["voice"], s["voice_kokoro"]), ("own", "dip_puck"))
            w1 = json.loads((ep / "voice" / "scene1.words.json").read_text())
            self.assertEqual([w["w"] for w in w1], "Throw away the left half.".split())
            self.assertLess(w1[0]["s"], 0.2)                        # timed from the start of its own clip


def _fake_generate(ws, slug, voice):
    """A generated AI voice without the voice server or ffmpeg (it must be generated before it can be approved)."""
    import wave
    ep = voice_desk._ep(ws, slug)
    staged = ep / "voice-take" / "scenes-ai"
    staged.mkdir(parents=True, exist_ok=True)
    for i in range(len(voice_desk.lines(json.loads((ep / "script.json").read_text())))):
        with wave.open(str(staged / f"scene{i}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(b"\0\0" * 4800)
    d = voice_desk._adopt(ep)
    d["voice"] = {"state": "ready", "mode": voice, "ai": {}}
    voice_desk._save_desk(ep, d)


class AiVoiceTests(unittest.TestCase):
    """dip_puck / am_puck are generated at once, listened to, regenerated from feedback, then approved (owner, 2026-11-18)."""
    def _ep(self, ws):
        root = ws.root / "shorts-factory"
        (root / "episodes").mkdir(parents=True)
        (root / "package.json").write_text("{}")
        cfg = ws.config()
        cfg["platforms"]["youtube"]["video"]["factory_path"] = str(root)
        ws.save_config(cfg)
        ep = root / "episodes" / "bloom"
        ep.mkdir()
        (ep / "script.json").write_text(json.dumps({"style": "iso", "beats": [{"say": "Start in the middle."}, {"say": "Say SQL. Then stop."}]}))
        return ep

    def test_generate_listen_feedback_and_approve(self):
        spoken = []
        def fake_tts(cfg, voice, text, out):
            spoken.append(text)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=0.8", "-ar", "48000", "-ac", "1", str(out)], check=True)
        sync = lambda slug, what, fn: fn()
        with TempWorkspace() as ws, mock.patch.object(voice_desk, "_ai_tts", fake_tts), mock.patch.object(voice_desk, "_start", sync):
            ep = self._ep(ws)
            with self.assertRaises(ValueError):          # nothing to approve before it is generated
                voice_desk.choose(ws, "bloom", "dip_puck")
            out = voice_desk.generate(ws, "bloom", "dip_puck")
            self.assertEqual(voice_desk.desk(ep)["voice"]["state"], "ready")
            self.assertTrue((ep / "voice-take" / "take-ai.wav").exists())
            self.assertEqual(spoken[:3], ["Start in the middle.", "Say SQL.", "Then stop."])   # sentence by sentence
            self.assertGreater(len(spoken), 3)                                                  # ... and the outro
            spoken.clear()
            change = {"say": {"SQL": "sequel"}, "lines": [2], "summary": "say SQL as sequel"}
            with mock.patch.object(voice_desk, "_feedback_to_changes", return_value=change):
                voice_desk.generate(ws, "bloom", "dip_puck", feedback="say SQL as sequel")
            self.assertIn("Say sequel.", spoken)
            ai = voice_desk.desk(ep)["voice"]["ai"]
            self.assertEqual(ai["say"], {"SQL": "sequel"})
            self.assertEqual(ai["feedback"][-1]["text"], "say SQL as sequel")
            first = (ep / "voice-take" / "scenes-ai" / "scene0.wav").stat().st_mtime_ns
            spoken.clear()
            with mock.patch.object(voice_desk, "_feedback_to_changes", return_value={"lines": [2], "summary": "line 2 again"}):
                voice_desk.generate(ws, "bloom", "dip_puck", feedback="line 2 sounds flat")
            self.assertEqual(spoken, ["Say sequel.", "Then stop."])   # only line 2, still with the respelling
            self.assertEqual((ep / "voice-take" / "scenes-ai" / "scene0.wav").stat().st_mtime_ns, first)
            voice_desk.choose(ws, "bloom", "dip_puck")
            self.assertTrue((ep / "voice" / "scene1.wav").exists())   # the video uses the take you heard
            s = json.loads((ep / "script.json").read_text())
            self.assertEqual((s["voice"], s["voice_kokoro"]), ("own", "dip_puck"))
            self.assertEqual(voice_desk.desk(ep)["voice"]["state"], "approved")

    def test_an_edited_line_is_read_again_by_itself(self):
        spoken = []
        def fake_tts(cfg, voice, text, out):
            spoken.append(text)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=0.5", "-ar", "48000", "-ac", "1", str(out)], check=True)
        with TempWorkspace() as ws, mock.patch.object(voice_desk, "_ai_tts", fake_tts), mock.patch.object(voice_desk, "_start", lambda s, w, fn: fn()):
            ep = self._ep(ws)
            voice_desk.generate(ws, "bloom", "am_puck")
            spoken.clear()
            voice_desk.save_lines(ws, "bloom", ["Start right in the middle.", "Say SQL. Then stop."])
            self.assertEqual(spoken, ["Start right in the middle."])
            self.assertEqual(voice_desk.desk(ep)["voice"]["state"], "ready")


if __name__ == "__main__":
    unittest.main()
