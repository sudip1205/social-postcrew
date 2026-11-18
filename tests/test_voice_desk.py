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

from postcrew import voice_desk  # noqa: E402
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
    def test_numbers_in_words_match_digits(self):
        self.assertEqual(voice_desk.tokens("Index forty-five holds 45."), ["index", "forty", "five", "holds", "forty", "five"])
        self.assertEqual(voice_desk.tokens("3,000 requests"), ["three", "thousand", "requests"])

    def test_a_retake_keeps_the_last_take_and_false_starts_are_cut(self):
        lines = ["Start in the middle. Index seven holds thirty-four.", "Throw away the left half."]
        words = (said("Start in the middle.", 0) + said("Index seven holds thirty five", 1.5) + said("sorry again", 3.2)
                 + said("Index seven holds 34.", 4.2) + said("Throw away the left half.", 6.0))
        sents = voice_desk.align(words, lines)
        self.assertEqual([s.get("missing", False) for s in sents], [False, False, False])
        second = sents[1]
        self.assertEqual(" ".join(w["w"] for w in words[second["i"]:second["j"]]), "Index seven holds 34.")   # the last take
        plan, removed, _ = voice_desk.plan_cuts(words, sents)
        self.assertTrue(any("sorry again" in r for r in removed))
        self.assertTrue(any("thirty five" in r for r in removed))   # the slipped first take
        self.assertEqual([line for line, _ in plan], [0, 1])

    def test_a_huge_gap_inside_a_sentence_is_shortened_but_normal_pauses_are_kept(self):
        words = said("Every check throws away", 0) + said("at least half.", 1.2 + 3.0)   # a 3 s hesitation in the middle
        words += said("Sixteen, eight, three, one.", 5.6, per=0.5)                        # slow on purpose: kept as it was
        sents = voice_desk.align(words, ["Every check throws away at least half. Sixteen, eight, three, one."])
        plan, _, shortened = voice_desk.plan_cuts(words, sents)
        segs = plan[0][1]
        self.assertEqual(segs[0][2], voice_desk.KEEP_GAP)          # the hesitation became a short pause
        self.assertGreaterEqual(shortened, 1)
        self.assertAlmostEqual(segs[1][2], words[7]["s"] - words[6]["e"], places=2)   # the pause between sentences as it was

    def test_a_line_that_was_not_recorded_is_reported_missing(self):
        sents = voice_desk.align(said("Line one is here."), ["Line one is here.", "Completely different words now."])
        self.assertTrue(sents[1]["missing"])


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
                ep = voice_desk.choose(ws, slug, "am_puck")
            self.assertEqual(ep["voice"]["state"], "approved")
            self.assertEqual(json.loads((root / "episodes" / slug / "script.json").read_text())["voice"], "am_puck")
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
            voice_desk.process(ws, slug, converter=conv, words_of=lambda f: words)
            rep = json.loads((ep / "voice-take" / "report.json").read_text())
            self.assertEqual(rep["kept_lines"], 2)
            self.assertEqual(rep["removed"], ["um"])
            self.assertFalse(rep["outro_recorded"])                 # the outro line is read by dip_puck
            self.assertEqual(voice_desk.desk(ep)["voice"]["state"], "ready")
            self.assertTrue((ep / "voice-take" / "scenes" / "scene1.wav").exists())
            with mock.patch.object(voice_desk, "_start"):
                voice_desk.choose(ws, slug, "own")
            self.assertTrue((ep / "voice" / "scene0.wav").exists())
            self.assertFalse((ep / "voice" / "scene2.wav").exists())
            s = json.loads((ep / "script.json").read_text())
            self.assertEqual((s["voice"], s["voice_kokoro"]), ("own", "dip_puck"))
            w1 = json.loads((ep / "voice" / "scene1.words.json").read_text())
            self.assertEqual([w["w"] for w in w1], "Throw away the left half.".split())
            self.assertLess(w1[0]["s"], 0.2)                        # timed from the start of its own clip


if __name__ == "__main__":
    unittest.main()
