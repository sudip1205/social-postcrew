"""The YouTube crew end to end, offline: script -> Editor -> voice -> video -> queue -> upload. A scripted AI, a fake
ElevenLabs (real small audio files made with ffmpeg) and a fake YouTube client."""
import io
import json
import shutil
import subprocess
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from helpers import ScriptedLLM, TempWorkspace, review, topic
from postcrew import assets, platforms, voice
from postcrew.agents import credentials as cred_mod
from postcrew.agents.publisher import publish_due
from postcrew.agents.script import finish
from postcrew.checks import script_problems
from postcrew.crew import run_crew
from postcrew.render import video as video_mod
from postcrew.workspace import validate_config
from postcrew.youtube import YouTubeError

HAVE_FFMPEG = bool(shutil.which("ffmpeg"))
DAY = date(2026, 11, 3)
CLAUDE_OK = {"state": "ok", "message": "logged in"}


WORDS = "apple river cloud stone bridge garden window candle forest anchor basket meadow".split()   # real words: the voice can say them


def narration(n_words, start="Step"):
    shift = sum(map(ord, start))
    return " ".join(WORDS[(shift + i * 5 + i // 12) % len(WORDS)] for i in range(n_words)) + "."


def script(words_per_scene=20, scenes=5, **over):
    sc = [{"layout": "title" if i == 0 else "statement", "narration": narration(words_per_scene, f"w{i}"),
           "on_screen": f"Point number {i + 1}", "items": [], "code": "", "language": "", "seconds": 8}
          for i in range(scenes)]
    out = {"title": "Why your default arguments surprise you", "description": "A quick look at Python default arguments and "
           "the one-line fix that stops them leaking between calls.", "tags": ["python", "tips", "debugging"],
           "thumbnail_text": "Default args", "scenes": sc}
    out.update(over)
    return finish(out)


def youtube_ws(ws, dry_run=False, approval="manual"):
    cfg = ws.config()
    yt = cfg["platforms"]["youtube"]
    yt["enabled"] = True
    yt["publishing"].update(dry_run=dry_run, approval=approval)
    cfg["profile"]["handle"] = "example.com/test"
    ws.save_config(cfg)
    ws.update_secrets(elevenlabs_api_key="xi-test", youtube_client_id="cid", youtube_client_secret="sec",
                      youtube_refresh_token="rt")
    cfg = ws.config()
    cfg["platforms"]["youtube"]["video"]["voice"].update(voice_id="v1", voice_name="Rachel")
    ws.save_config(cfg)
    return ws


def fake_tts(root, text, voice_cfg, api_key, opener=None, **kw):   # kw: align, before, after (the voice step passes the neighbouring scenes)
    """An audio clip as long as the text would take to say (2.5 words a second), made with ffmpeg."""
    secs = max(0.6, len(text.split()) / 2.5 / 8)   # eight times faster than real speech: keeps the test quick
    out = Path(root) / "cache" / "voice" / f"fake-{abs(hash(text))}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=330:duration={secs}",
                    "-q:a", "9", str(out)], check=True)
    return {"path": str(out), "seconds": secs, "characters": len(text)}


class FakeYouTube:
    uploads, fail = [], None

    def __init__(self, cid, secret, refresh, opener=None):
        pass

    def channel(self):
        return {"id": "UC1", "title": "My Channel"}

    def upload(self, path, title, description, tags, category_id="28", privacy="private", publish_at=None,
               made_for_kids=False, progress=None):
        if FakeYouTube.fail:
            raise FakeYouTube.fail
        FakeYouTube.uploads.append({"path": str(path), "title": title, "description": description, "tags": tags,
                                    "privacy": privacy})
        return {"id": "vid123", "url": "https://www.youtube.com/watch?v=vid123"}

    def set_thumbnail(self, video_id, image_path):
        FakeYouTube.uploads[-1]["thumbnail"] = str(image_path)


class ScriptCheckTests(unittest.TestCase):
    spec = {"format": "short", "target_seconds": 45, "max_words": 112}
    profile = {"blocklist": ["my employer"], "about": []}
    cat = {"label": "x"}

    def test_a_good_script_passes(self):
        self.assertEqual(script_problems(script(), self.spec, self.cat, self.profile), [])

    def test_length_scenes_and_metadata_are_checked(self):
        long = script(words_per_scene=40)          # 200 words for a 45 s Short
        self.assertTrue(any("Cut" in p for p in script_problems(long, self.spec, self.cat, self.profile)))
        short = script(words_per_scene=5)
        self.assertTrue(any("only" in p for p in script_problems(short, self.spec, self.cat, self.profile)))
        two = script(scenes=2, words_per_scene=45)
        self.assertTrue(any("2 scenes" in p for p in script_problems(two, self.spec, self.cat, self.profile)))
        bad = script(title="Short", tags=["a"], thumbnail_text="")
        text = " ".join(script_problems(bad, self.spec, self.cat, self.profile))
        for frag in ("title", "tags", "thumbnail_text"):
            self.assertIn(frag, text)

    def test_teaching_style_rules_long_sentences_and_pause_tags(self):
        s = script()
        long = " ".join(["word"] * 34) + "."
        s["scenes"][1]["narration"] = long
        s = finish(s)
        self.assertTrue(any("sentence of 34 words" in p for p in script_problems(s, self.spec, self.cat, self.profile)), s)
        s = script()
        s["scenes"][2]["narration"] = "Here is the idea. [pause] Now the next part."
        s = finish(s)
        self.assertTrue(any("no [pause] or <break>" in p for p in script_problems(s, self.spec, self.cat, self.profile)))
        s = script()
        s["scenes"][2]["narration"] = "Here is the idea... Now the next part."
        self.assertEqual([p for p in script_problems(finish(s), self.spec, self.cat, self.profile) if "pause" in p or "sentence" in p], [])

    def test_filler_urls_markdown_and_blocked_phrases_are_rejected(self):
        s = script()
        s["scenes"][0]["narration"] = "Hey guys, visit https://example.com and **smash** my employer " + narration(15)
        s = finish(s)
        text = " ".join(script_problems(s, self.spec, self.cat, self.profile))
        for frag in ("filler", "web address", "markdown", "blocked"):
            self.assertIn(frag, text)

    def test_code_scenes_must_parse(self):
        s = script()
        s["scenes"][1].update(layout="code", code="def f(:\n  pass", language="python")
        self.assertTrue(any("scene 2" in p for p in script_problems(s, self.spec, self.cat, self.profile)))


class VideoSpecTests(unittest.TestCase):
    def test_later_settings_win_and_lengths_are_clamped(self):
        cfg = {"video": {"format": "short", "target_seconds": 45}}
        self.assertEqual(platforms.video_spec(cfg)["max_words"], 112)
        self.assertEqual(platforms.video_spec(cfg, {"format": "long", "target_seconds": 600})["target_seconds"], 600)
        self.assertEqual(platforms.video_spec(cfg, {"target_seconds": 600})["target_seconds"], 180)   # a Short stays a Short (3 min)
        self.assertEqual(platforms.video_spec(cfg, {}, {"format": "long"}, {"target_seconds": 300})["target_seconds"], 300)

    def test_config_validation_covers_the_video_settings(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            self.assertEqual(validate_config(cfg), [])
            cfg["platforms"]["youtube"]["enabled"] = True
            cfg["platforms"]["youtube"]["video"].update(format="short", target_seconds=300, renderer="mcp")
            cfg["platforms"]["youtube"]["categories"]["explainer"]["target_seconds"] = 5
            errs = " | ".join(validate_config(cfg))
            for frag in ("video.target_seconds", "video.mcp", "explainer.target_seconds"):
                self.assertIn(frag, errs)


class AssetTests(unittest.TestCase):
    def test_script_file_becomes_scenes_and_bad_files_are_refused(self):
        text = ("title: Why JWTs leak\ntags: jwt, auth, security\n\nYour login token can leak from a log file.\n"
                "on-screen: Tokens in logs\n\nHere is the fix:\n- Strip the header\n- Log a hash\n\n"
                "```python\nprint(1)\n```\nThen check it.\n")
        s = assets.parse_script(text)
        self.assertEqual((s["title"], s["tags"]), ("Why JWTs leak", ["jwt", "auth", "security"]))
        self.assertEqual([x["layout"] for x in s["scenes"]], ["title", "points", "code"])
        self.assertEqual(s["scenes"][1]["items"], ["Strip the header", "Log a hash"])
        with self.assertRaises(assets.AssetError):
            assets.parse_script("title: only metadata")

    def test_save_replaces_limits_and_remove(self):
        with TempWorkspace() as ws:
            d = DAY.isoformat()
            assets.save_stream(ws, "youtube", d, "script", "my.md", io.BytesIO(b"hello world"), 11)
            assets.save_stream(ws, "youtube", d, "script", "other.txt", io.BytesIO(b"second"), 6)
            found = assets.find(ws, "youtube", d)
            self.assertEqual(list(found), ["script"])
            self.assertEqual(found["script"].read_text(), "second")
            self.assertEqual(assets.original_name(found["script"]), "other.txt")
            with self.assertRaises(assets.AssetError):
                assets.save_stream(ws, "youtube", d, "voice", "x.exe", io.BytesIO(b"x"), 1)
            with self.assertRaises(assets.AssetError):
                assets.save_stream(ws, "youtube", d, "script", "big.txt", io.BytesIO(b""), 300_000)
            with self.assertRaises(assets.AssetError):
                assets.save_stream(ws, "../x", d, "script", "a.txt", io.BytesIO(b"x"), 1)
            assets.remove(ws, "youtube", d, "script")
            self.assertEqual(assets.find(ws, "youtube", d), {})


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
@mock.patch.object(cred_mod, "check_claude", return_value=CLAUDE_OK)
@mock.patch.object(voice, "cached_synthesize", side_effect=fake_tts)
class YouTubeCrewTests(unittest.TestCase):
    def llm(self, **over):
        s = {"topic": [topic("Default arguments", ())], "writer": [script()], "editor": [review()]}
        s.update(over)
        return ScriptedLLM(s)

    def run_short(self, ws, llm=None, **kw):
        return run_crew(ws, DAY, "short-tip", llm=llm or self.llm(), platform="youtube", **kw)

    def test_a_short_is_made_reviewed_voiced_rendered_and_queued(self, _tts, _claude):
        with TempWorkspace() as ws:
            youtube_ws(ws)
            llm = self.llm()
            res = self.run_short(ws, llm)
            self.assertTrue(res["ok"], res)
            steps = json.loads((ws.runs_dir / res["run_id"] / "status.json").read_text())["steps"]
            self.assertEqual({k: v["state"] for k, v in steps.items()},
                             {**{s: "passed" for s in ("credentials", "topic", "research", "writer", "editor", "voice", "media",
                                                      "hooks", "publisher")}, "video_review": "skipped"})   # slides videos: no second review
            self.assertEqual(llm.agents_called().count("editor"), 3)      # reviewed like any post
            post = ws.queue()[0]
            self.assertEqual((post["platform"], post["status"], post["id"]), ("youtube", "awaiting_approval",
                                                                             "2026-11-03-youtube-short-tip"))
            yt = post["youtube"]
            self.assertEqual((yt["format"], yt["voice"], yt["source"]["voice"]), ("short", "Rachel", "crew"))
            info = video_mod.probe(ws.root / post["media"])
            self.assertEqual((info["width"], info["height"]), (1080, 1920))
            self.assertTrue(info["has_audio"])
            self.assertTrue((ws.root / post["poster_image"]).stat().st_size > 1000)   # the thumbnail
            self.assertTrue(post["scheduled_at"].startswith("2026-11-03T23:00"))      # 17:00 Chicago (CST after the clocks change)

    def test_the_voice_is_only_made_after_the_editor_passes(self, tts, _claude):
        with TempWorkspace() as ws:
            youtube_ws(ws)
            llm = self.llm(editor=[review(60, owner="writer", fixes=["Scene 1: shorten the hook"]), review()],
                           supervisor=[{"action": "rewind", "target": "writer", "instructions": ["fix"], "reason": "weak"}],
                           writer=[script(), script(words_per_scene=19)])
            res = self.run_short(ws, llm)
            self.assertTrue(res["ok"], res)
            self.assertEqual(llm.agents_called().count("writer"), 2)
            self.assertEqual(tts.call_count, 5)       # one clip per scene, once: nothing was spent on the rejected script

    def test_rehearsal_spends_no_voice_characters_and_queues_nothing(self, tts, _claude):
        with TempWorkspace() as ws:
            youtube_ws(ws)
            res = self.run_short(ws, dry_run=True)
            self.assertTrue(res["ok"], res)
            tts.assert_not_called()
            self.assertEqual(ws.queue(), [])

    def test_a_script_that_breaks_the_rules_is_sent_back_before_any_review(self, _tts, _claude):
        with TempWorkspace() as ws:
            youtube_ws(ws)
            bad = script(words_per_scene=60)          # 300 words for a 45 s Short
            llm = self.llm(writer=[bad, script()])
            res = self.run_short(ws, llm)
            self.assertTrue(res["ok"], res)
            self.assertEqual(llm.agents_called().count("writer"), 2)

    def test_missing_elevenlabs_key_stops_with_a_clear_reason(self, _tts, _claude):
        with TempWorkspace() as ws:
            youtube_ws(ws)
            ws.update_secrets(elevenlabs_api_key="")
            res = self.run_short(ws)
            self.assertFalse(res["ok"])
            self.assertIn("ElevenLabs", " ".join(res["problems"]))

    def test_the_owners_own_script_and_voice_skip_those_steps(self, tts, _claude):
        with TempWorkspace() as ws:
            youtube_ws(ws)
            body = "\n\n".join(narration(20, f"mine{i}") for i in range(5)).encode()
            assets.save_stream(ws, "youtube", DAY.isoformat(), "script", "s.txt", io.BytesIO(body), len(body))
            wav = ws.root / "own.mp3"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=12", "-q:a", "9", str(wav)],
                           check=True)
            data = wav.read_bytes()
            assets.save_stream(ws, "youtube", DAY.isoformat(), "voice", "v.mp3", io.BytesIO(data), len(data))
            llm = self.llm(writer=[])
            res = self.run_short(ws, llm)
            self.assertTrue(res["ok"], res)
            self.assertNotIn("writer", llm.agents_called())     # no drafting: the script is theirs
            self.assertIn("editor", llm.agents_called())        # ...but it is still reviewed
            tts.assert_not_called()
            yt = ws.queue()[0]["youtube"]
            self.assertEqual((yt["source"]["script"], yt["source"]["voice"]), ("own", "own"))
            self.assertAlmostEqual(yt["seconds"], 12, delta=1.5)  # the voice sets the length

    def test_the_owners_own_video_is_checked_and_used_as_it_is(self, _tts, _claude):
        with TempWorkspace() as ws:
            youtube_ws(ws)
            mp4 = ws.root / "own.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=3",
                            "-f", "lavfi", "-i", "sine=duration=3", "-shortest", "-pix_fmt", "yuv420p", str(mp4)], check=True)
            data = mp4.read_bytes()
            assets.save_stream(ws, "youtube", DAY.isoformat(), "video", "v.mp4", io.BytesIO(data), len(data))
            res = self.run_short(ws)
            self.assertTrue(res["ok"], res)
            self.assertEqual(ws.queue()[0]["youtube"]["source"]["video"], "own")
            wide = ws.root / "wide.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=3",
                            "-f", "lavfi", "-i", "sine=duration=3", "-shortest", "-pix_fmt", "yuv420p", str(wide)], check=True)
            data = wide.read_bytes()
            ws.save_queue([])
            assets.save_stream(ws, "youtube", DAY.isoformat(), "video", "v.mp4", io.BytesIO(data), len(data))
            res = self.run_short(ws)
            self.assertFalse(res["ok"])                          # a landscape video cannot be a Short
            self.assertIn("does not fit", " ".join(res["problems"]))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
@mock.patch.object(cred_mod, "check_claude", return_value=CLAUDE_OK)
@mock.patch.object(voice, "cached_synthesize", side_effect=fake_tts)
class YouTubePublishTests(unittest.TestCase):
    def queued(self, ws, approval="auto_with_veto"):
        youtube_ws(ws, dry_run=False, approval=approval)
        llm = ScriptedLLM({"topic": [topic("Default arguments", ())], "writer": [script()], "editor": [review()]})
        self.assertTrue(run_crew(ws, DAY, "short-tip", llm=llm, platform="youtube")["ok"])
        return ws.queue()[0]

    def due(self, post):
        return datetime.fromisoformat(post["scheduled_at"]).replace(year=2030)

    def test_a_due_video_is_uploaded_with_its_thumbnail_and_moves_to_history(self, _tts, _claude):
        FakeYouTube.uploads, FakeYouTube.fail = [], None
        with TempWorkspace() as ws:
            post = self.queued(ws)
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual([r["status"] for r in res], ["published"])
            up = FakeYouTube.uploads[0]
            self.assertEqual(up["privacy"], "public")
            self.assertTrue(up["description"].endswith("#Shorts"))      # a Short is filed under Shorts
            self.assertTrue(up["thumbnail"].endswith(".png"))
            self.assertEqual(ws.queue(), [])
            hist = ws.history()[-1]
            self.assertEqual((hist["platform"], hist["youtube"]["url"]), ("youtube", "https://www.youtube.com/watch?v=vid123"))

    def test_nothing_is_uploaded_before_approval_or_in_practice_mode(self, _tts, _claude):
        FakeYouTube.uploads, FakeYouTube.fail = [], None
        with TempWorkspace() as ws:
            post = self.queued(ws, approval="manual")
            self.assertEqual(publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None), [])
            cfg = ws.config()
            cfg["platforms"]["youtube"]["publishing"].update(approval="auto_with_veto", dry_run=True)
            ws.save_config(cfg)
            q = ws.queue()
            q[0]["status"] = "queued"
            ws.save_queue(q)
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual([r["status"] for r in res], ["dry_run"])
            self.assertEqual(FakeYouTube.uploads, [])

    def test_quota_and_auth_errors_keep_the_video_queued_and_other_errors_fail_it(self, _tts, _claude):
        with TempWorkspace() as ws:
            post = self.queued(ws)
            FakeYouTube.fail = YouTubeError("quota used up", "quota")
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual(res[0]["status"], "queued")
            FakeYouTube.fail = YouTubeError("bad file", "invalid")
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual(res[0]["status"], "failed")
        FakeYouTube.fail = None

    def test_a_disconnected_channel_blocks_the_upload(self, _tts, _claude):
        FakeYouTube.fail = None
        with TempWorkspace() as ws:
            post = self.queued(ws)
            ws.update_secrets(youtube_refresh_token="")
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual(res[0]["status"], "queued")
            self.assertIn("Connect YouTube", res[0]["error"])


if __name__ == "__main__":
    unittest.main()


class FindabilityTests(unittest.TestCase):
    """Tags, hashtags and chapters that help a video be found."""

    def test_tags_are_cleaned_and_kept_within_youtubes_limits(self):
        from postcrew import seo
        tags = seo.normalize_tags(["#Circuit breaker pattern", "circuit breaker pattern", "x" * 31, "System Design, interview"] + [f"tag number {n}" for n in range(40)])
        self.assertEqual(tags[0], "Circuit breaker pattern")
        self.assertNotIn("x" * 31, tags)
        self.assertEqual(len({t.lower() for t in tags}), len(tags))
        self.assertLessEqual(len(tags), 15)
        self.assertLessEqual(sum(len(t) + 1 + (2 if " " in t else 0) for t in tags), 460)

    def test_three_hashtags_come_from_the_first_tags_unless_the_description_has_them(self):
        from postcrew import seo
        self.assertEqual(seo.with_hashtags("Learn it.", ["circuit breaker pattern", "microservices", "system design", "x"]).splitlines()[-1],
                         "#CircuitBreakerPattern #Microservices #SystemDesign")
        self.assertEqual(seo.with_hashtags("Learn it. #A #B #C", ["x tag"]), "Learn it. #A #B #C")

    def test_chapters_use_the_real_scene_lengths_and_only_for_a_long_video(self):
        from postcrew import seo
        scenes = [{"on_screen": "Why it matters", "seconds": 12}, {"on_screen": "The request path", "seconds": 18},
                  {"on_screen": "A quick note", "seconds": 4}, {"on_screen": "Three states", "seconds": 20},
                  {"on_screen": "Like · Comment · Share", "seconds": 7, "closing": True}]
        self.assertEqual(seo.chapters(scenes, "long").splitlines(), ["0:00 Introduction", "0:12 The request path", "0:34 Three states"])
        self.assertEqual(seo.chapters(scenes, "short"), "")
        self.assertEqual(seo.chapters(scenes[:2], "long"), "")   # fewer than three chapters is not a valid set

    def test_the_uploaded_description_has_chapters_and_hashtags(self):
        from postcrew.agents.yt_publish import full_description
        post = {"youtube": {"description": "Circuit breakers explained.\n\nWhat you will learn.", "format": "long",
                            "tags": ["circuit breaker pattern", "microservices", "system design"],
                            "scenes": [{"on_screen": "x", "seconds": 15}, {"on_screen": "Request path", "seconds": 20},
                                       {"on_screen": "Three states", "seconds": 25}, {"on_screen": "Like", "seconds": 6, "closing": True}]}}
        d = full_description(post)
        self.assertIn("Chapters\n0:00 Introduction\n0:15 Request path\n0:35 Three states", d)
        self.assertTrue(d.rstrip().endswith("#CircuitBreakerPattern #Microservices #SystemDesign"))
        post["youtube"].update(format="short")
        s = full_description(post)
        self.assertNotIn("Chapters", s)
        self.assertTrue(s.rstrip().endswith("#Shorts"))
