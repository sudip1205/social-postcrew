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
    words = [WORDS[(shift + i * 5 + i // 12) % len(WORDS)] for i in range(n_words)]
    for k, w in ((3, "you"), (9, "let's")):   # a teacher speaks to the student
        if k < n_words and start != "Step":
            words[k] = w
    if start == "w0" and n_words > 12:
        words[11] = "imagine"
    text = " ".join(w + ("." if (i + 1) % 12 == 0 and i + 1 < n_words else "") for i, w in enumerate(words)) + "."   # short sentences: a voice can say them
    return text[:-1] + "?" if start == "w1" else text   # one question to the class


def _scene(i, words_per_scene, scenes):
    text = narration(words_per_scene, f"w{i}")
    a, b = (w.strip(".") for w in text.split()[:2])
    if i == 0:
        return {"layout": "title", "narration": text, "on_screen": "Point number 1", "items": [], "code": "", "language": "", "seconds": 8}
    if i == scenes - 1 and scenes > 3:   # a words-only scene now and then is fine; most scenes are pictures
        return {"layout": "statement", "narration": text, "on_screen": f"Point number {i + 1}", "items": [], "code": "", "language": "", "seconds": 8}
    return {"layout": "diagram", "narration": text, "on_screen": f"Point number {i + 1}", "items": [], "code": "", "language": "", "seconds": 8,
            "nodes": [a.capitalize(), b.capitalize()], "edges": [f"{a.capitalize()} > {b.capitalize()}: go"]}


def script(words_per_scene=32, scenes=5, **over):
    sc = [_scene(i, words_per_scene, scenes) for i in range(scenes)]
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
    spec = {"format": "short", "target_seconds": 75, "max_words": 187, "min_words": 131}
    profile = {"blocklist": ["my employer"], "about": []}
    cat = {"label": "x"}

    def test_a_good_script_passes(self):
        self.assertEqual(script_problems(script(), self.spec, self.cat, self.profile), [])

    def test_length_scenes_and_metadata_are_checked(self):
        long = script(words_per_scene=48)          # longer than the guide: the length is free, so no complaint about the length
        self.assertFalse(any("Cut" in p or "should run" in p for p in script_problems(long, self.spec, self.cat, self.profile)))
        over = script(words_per_scene=80, scenes=8)  # a Short over three minutes cannot be a Short
        self.assertTrue(any("3 minutes" in p for p in script_problems(over, self.spec, self.cat, self.profile)))
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
        cfg = {"video": {"format": "short", "target_seconds": 75}}
        self.assertEqual(platforms.video_spec(cfg)["max_words"], 150)   # clamped to the owner's 60 s (2026-11-12)
        self.assertEqual(platforms.video_spec({"video": {"format": "short", "target_seconds": 45}})["target_seconds"], 45)   # the length is a guide
        self.assertEqual(platforms.video_spec(cfg, {"format": "long", "target_seconds": 600})["target_seconds"], 600)
        self.assertEqual(platforms.video_spec(cfg, {"target_seconds": 600})["target_seconds"], 60)   # a Short stays a Short (at most a minute, the owner's limit)
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
class YouTubePublishTests(unittest.TestCase):
    def queued(self, ws, approval="auto_with_veto"):
        """A video made by the Shorts factory (faked: tests/test_shorts.py) and queued."""
        from test_shorts import fake_factory
        youtube_ws(ws, dry_run=False, approval=approval)
        with fake_factory(ws):
            res = run_crew(ws, DAY, "short-tip", platform="youtube")
        self.assertTrue(res["ok"], res)
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
            self.assertTrue(up["thumbnail"].endswith(".jpg"))   # the factory's own thumbnail
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

    def test_a_different_channel_stops_the_upload_until_approved_again(self, _tts, _claude):
        FakeYouTube.uploads, FakeYouTube.fail = [], None
        from postcrew.studio.server import Studio
        with TempWorkspace() as ws:
            post = self.queued(ws)
            ws.save_state("youtube_channel", {"id": "UC-brand", "title": "Dip-to-Dive"})   # where the videos went until now
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual(res[0]["status"], "awaiting_approval")
            self.assertIn('connected to the channel "My Channel"', res[0]["error"])
            self.assertEqual(FakeYouTube.uploads, [])                        # nothing went to the other channel
            Studio(ws).queue_action(post["id"], "approve", {})               # you choose the new channel
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual(res[0]["status"], "published")
            self.assertEqual(res[0]["youtube"]["channel"], "My Channel")
            self.assertEqual(ws.state("youtube_channel")["id"], "UC1")      # the new channel is remembered

    def test_the_first_upload_remembers_its_channel(self, _tts, _claude):
        FakeYouTube.uploads, FakeYouTube.fail = [], None
        with TempWorkspace() as ws:
            post = self.queued(ws)
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual(res[0]["status"], "published")
            self.assertEqual(ws.state("youtube_channel"), {"id": "UC1", "title": "My Channel"})

    def test_a_disconnected_channel_blocks_the_upload(self, _tts, _claude):
        FakeYouTube.fail = None
        with TempWorkspace() as ws:
            post = self.queued(ws)
            ws.update_secrets(youtube_refresh_token="")
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual(res[0]["status"], "queued")
            self.assertIn("Connect YouTube", res[0]["error"])

    def meta_ready(self, ws):
        from postcrew.agents.shorts import factory_dir
        f = factory_dir(platforms.view(ws.config(), "youtube")) / "secrets" / "meta.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"pageId": "P1", "igUserId": "IG1", "pageAccessToken": "tok", "graphVersion": "v23.0"}))

    def test_a_short_on_youtube_also_goes_to_facebook_and_instagram(self, _tts, _claude):
        FakeYouTube.uploads, FakeYouTube.fail = [], None
        FakeMeta.calls, FakeMeta.fail = [], set()
        with TempWorkspace() as ws, mock.patch("postcrew.meta.Meta", FakeMeta), mock.patch("postcrew.meta.seconds", return_value=40.0), \
                mock.patch("postcrew.meta.cover", return_value=(Path("media/x.cover.jpg"), 2.5)):
            post = self.queued(ws)
            self.meta_ready(ws)
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual(res[0]["status"], "published")
            self.assertEqual([c[0] for c in FakeMeta.calls], ["facebook", "thumbnail", "instagram"])
            self.assertTrue(FakeMeta.calls[1][1].endswith(".cover.jpg"))
            self.assertEqual(FakeMeta.calls[2][2], "fb1")   # Instagram may fall back to the Facebook copy
            cap = FakeMeta.calls[0][1]
            self.assertTrue(cap.startswith(post["youtube"]["title"]))
            self.assertNotIn("#Shorts", cap)
            meta = ws.history()[-1]["meta"]
            self.assertEqual((meta["facebook"]["url"], meta["instagram"]["url"]),
                             ("https://www.facebook.com/reel/fb1", "https://www.instagram.com/reel/ig1/"))

    def test_a_failed_reel_is_tried_again_later_and_never_posted_twice(self, _tts, _claude):
        FakeYouTube.uploads, FakeYouTube.fail = [], None
        FakeMeta.calls, FakeMeta.fail = [], {"instagram"}
        with TempWorkspace() as ws, mock.patch("postcrew.meta.Meta", FakeMeta), mock.patch("postcrew.meta.seconds", return_value=40.0), \
                mock.patch("postcrew.meta.cover", return_value=(Path("media/x.cover.jpg"), 2.5)):
            post = self.queued(ws)
            self.meta_ready(ws)
            publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            meta = ws.history()[-1]["meta"]
            self.assertEqual((meta["facebook"]["status"], meta["instagram"]["status"]), ("published", "failed"))
            FakeMeta.fail = set()
            publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)   # the next publish window
            self.assertEqual([c[0] for c in FakeMeta.calls], ["facebook", "thumbnail", "instagram", "instagram"])
            self.assertEqual(ws.history()[-1]["meta"]["instagram"]["status"], "published")
            self.assertEqual(len(FakeYouTube.uploads), 1)

    def test_a_short_longer_than_a_reel_goes_to_facebook_as_a_page_video(self, _tts, _claude):
        FakeYouTube.uploads, FakeYouTube.fail = [], None
        FakeMeta.calls, FakeMeta.fail = [], set()
        with TempWorkspace() as ws, mock.patch("postcrew.meta.Meta", FakeMeta), mock.patch("postcrew.meta.seconds", return_value=140.0), \
                mock.patch("postcrew.meta.cover", return_value=(Path("media/x.cover.jpg"), 2.5)):
            post = self.queued(ws)
            self.meta_ready(ws)
            publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual([c[0] for c in FakeMeta.calls], ["facebook-video", "thumbnail"])   # too long for Instagram's API
            self.assertEqual(ws.history()[-1]["meta"]["instagram"]["status"], "too_long")
            self.assertEqual(ws.history()[-1]["meta"]["facebook"]["url"], "https://www.facebook.com/P1/videos/fb2")

    def test_a_short_too_long_for_instagrams_api_is_marked_not_retried(self, _tts, _claude):
        FakeYouTube.uploads, FakeYouTube.fail = [], None
        FakeMeta.calls, FakeMeta.fail = [], set()
        with TempWorkspace() as ws, mock.patch("postcrew.meta.Meta", FakeMeta), mock.patch("postcrew.meta.seconds", return_value=70.0), \
                mock.patch("postcrew.meta.cover", return_value=(Path("media/x.cover.jpg"), 2.5)):
            post = self.queued(ws)
            self.meta_ready(ws)
            publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual([c[0] for c in FakeMeta.calls], ["facebook", "thumbnail"])
            ig = ws.history()[-1]["meta"]["instagram"]
            self.assertEqual(ig["status"], "too_long")
            folder = ws.root / ig["folder"]   # ready to post by hand in the Instagram app
            self.assertTrue(folder.parent.name == "instagram" and (folder / "video.mp4").exists())
            self.assertIn("#", (folder / "caption.txt").read_text())
            details = (folder / "details.txt").read_text()
            self.assertIn("1:10", details)
            self.assertIn("https://www.facebook.com/", details)

    def test_without_a_meta_connection_youtube_still_publishes(self, _tts, _claude):
        FakeYouTube.uploads, FakeYouTube.fail = [], None
        FakeMeta.calls = []
        with TempWorkspace() as ws, mock.patch("postcrew.meta.Meta", FakeMeta):
            post = self.queued(ws)
            res = publish_due(ws, now=self.due(post), yt_factory=FakeYouTube, log=lambda m: None)
            self.assertEqual(res[0]["status"], "published")
            self.assertEqual(FakeMeta.calls, [])
            self.assertIn("not connected", ws.history()[-1]["meta"]["skipped"])


class MetaClientTests(unittest.TestCase):
    def test_facebook_not_knowing_a_new_video_for_a_moment_is_not_a_failure(self):
        from postcrew.meta import Meta, MetaError
        m = Meta("P1", "IG1", "tok", sleep=lambda s: None)
        answers = iter([MetaError("GET 400: does not exist"), MetaError("GET 400: does not exist"), {"status": {"video_status": "ready"}}])

        def api(method, path, params=None, headers=None, body=None):
            a = next(answers)
            if isinstance(a, Exception):
                raise a
            return a
        m.api = api
        m._wait_ready("v1")   # no exception
        self.assertIsNone(next(answers, None))


class FakeMeta:
    calls, fail = [], set()

    def __init__(self, page_id, ig_user_id, token, version="v23.0", ig_token=None):
        assert (page_id, ig_user_id, token) == ("P1", "IG1", "tok")

    def facebook_reel(self, video, caption, log=print):
        FakeMeta.calls.append(("facebook", caption, None))
        if "facebook" in FakeMeta.fail:
            from postcrew.meta import MetaError
            raise MetaError("fb down")
        return {"id": "fb1", "url": "https://www.facebook.com/reel/fb1"}

    def facebook_video(self, video, caption, title="", log=print):
        FakeMeta.calls.append(("facebook-video", caption, None))
        return {"id": "fb2", "url": "https://www.facebook.com/P1/videos/fb2"}

    def set_thumbnail(self, video_id, image):
        FakeMeta.calls.append(("thumbnail", str(image), video_id))
        return {"success": True}

    def instagram_reel(self, video, caption, facebook_id=None, log=print, thumb_ms=None):
        FakeMeta.calls.append(("instagram", caption, facebook_id))
        if "instagram" in FakeMeta.fail:
            from postcrew.meta import MetaError
            raise MetaError("ig busy")
        return {"id": "ig1", "url": "https://www.instagram.com/reel/ig1/"}


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


class VideoArcTests(unittest.TestCase):
    """Every video: intro, the problem (with an example), the idea drawn as to a child (small cases, then bigger), the pattern, the ways to code it, then the solution and its code, an example, a common mistake and the closing card."""
    ARC = ("intro", "problem", "visual", "visual", "conclusion", "approaches", "idea", "idea", "example", "mistake", "closing")
    DRAWN = {"visual": "paths", "conclusion": "points", "approaches": "flow", "mistake": "flow"}

    def arc(self, parts=None, **layouts):
        return [{"part": p, "layout": layouts.get(p, self.DRAWN.get(p, "statement"))} for p in (parts or self.ARC)]

    def without(self, *gone):
        return self.arc([p for p in self.ARC if p not in gone])

    def test_the_arc_is_checked(self):
        from postcrew.checks import structure_problems
        self.assertEqual(structure_problems(self.arc()), [])
        words = [dict(sc, layout="points") if sc["part"] == "mistake" else sc for sc in self.arc()]
        self.assertTrue(any("must be a picture" in m for m in structure_problems(words)))   # the mistake is shown, not listed
        self.assertEqual(structure_problems([{}, {}]), [])                       # an owner's own script says no parts: not checked
        self.assertTrue(any("introduction" in m for m in structure_problems(self.without("intro"))))
        self.assertTrue(any("'mistake'" in m for m in structure_problems(self.without("mistake"))))
        swapped = self.arc(("intro", "problem", "visual", "visual", "conclusion", "approaches", "example", "idea", "mistake", "closing"))
        self.assertTrue(any("out of order" in m for m in structure_problems(swapped)))
        self.assertTrue(any("closing" in m for m in structure_problems(self.arc(self.ARC[:-1]))))

    def test_the_problem_and_the_ways_come_before_the_solution(self):
        from postcrew.checks import structure_problems
        self.assertTrue(any("part 'problem'" in m and "what is asked" in m for m in structure_problems(self.without("problem"))))
        self.assertTrue(any("part 'approaches'" in m and "before any solution or code" in m for m in structure_problems(self.without("approaches"))))
        jump = structure_problems(self.arc(("intro", "idea", "problem", "visual", "visual", "conclusion", "approaches", "idea", "example", "mistake", "closing")))
        self.assertTrue(any("out of order" in m and "BEFORE the solution" in m for m in jump))   # the solution first, the problem after

    def test_the_idea_is_drawn_in_plain_words_before_the_code(self):
        from postcrew.checks import structure_problems
        self.assertTrue(any("part 'visual'" in m and "in plain words" in m for m in structure_problems(self.without("visual"))))
        self.assertTrue(any("part 'conclusion'" in m for m in structure_problems(self.without("conclusion"))))
        one = structure_problems(self.arc(("intro", "problem", "visual", "conclusion", "approaches", "idea", "example", "mistake", "closing")))
        self.assertTrue(any("at least two pictures" in m for m in one))           # the cases must grow
        words = structure_problems(self.arc(visual="statement"))
        self.assertTrue(any("every 'visual' scene is a drawing" in m for m in words))
        code_first = self.arc()
        code_first[2]["layout"] = "code"
        self.assertTrue(any("every 'visual' scene is a drawing" in m or "no code before the conclusion" in m for m in structure_problems(code_first)))
        early = self.arc()
        early[1]["layout"] = "codeviz"                                              # code in the problem part, before the pictures and the conclusion
        self.assertTrue(any("no code before the conclusion" in m for m in structure_problems(early)))
        plain_end = structure_problems(self.arc(conclusion="statement"))
        self.assertTrue(any("'conclusion' scene shows the pattern" in m for m in plain_end))

    def test_the_ways_are_shown_not_only_said(self):
        from postcrew.checks import structure_problems
        self.assertEqual(structure_problems(self.arc(approaches="points")), [])
        self.assertEqual(structure_problems(self.arc(approaches="diagram")), [])
        said = structure_problems(self.arc(approaches="statement"))
        self.assertTrue(any("'approaches' scene must show the ways" in m for m in said))


class EditorVideoRulesTests(unittest.TestCase):
    def test_the_editor_does_not_approve_a_script_without_the_story_even_when_the_reviewer_is_happy(self):
        from postcrew.agents import editor
        scenes = [{"part": p, "layout": "statement", "narration": "x"} for p in ("idea", "example", "closing")]
        seen = []

        class Ctx:
            platform = "youtube"
            outputs = {"writer": {"scenes": scenes, "text": "x"}}
            reviews = []
            cfg = {"pipeline": {"review_runs": 1, "min_overall": 70, "min_subscore": 60}}

        ag = editor.EditorAgent.__new__(editor.EditorAgent)
        ag.prompt = lambda ctx, **k: "system"
        ag.ask = lambda ctx, system, material, schema: seen.append(material) or {
            "overall": 95, "scores": {k: 95 for k in editor.CRITERIA}, "red_flags": [], "fixes": [], "fix_owner": "writer", "reasons": ""}
        from unittest import mock
        with mock.patch.object(editor, "review_material", lambda ctx, draft=None: "material"):
            out = ag.run(Ctx, None)
        self.assertFalse(out["passed"])
        self.assertTrue(any("introduction" in r for r in out["rules"]) and any("'mistake'" in r for r in out["rules"]))
        self.assertTrue(ag.validate(Ctx, out))


class StoryboardTests(unittest.TestCase):
    def test_most_scenes_must_be_pictures(self):
        from postcrew.checks import storyboard_problems
        wordy = [{"layout": "diagram", "part": "intro", "nodes": ["A", "B"], "narration": "a b"}] + \
                [{"layout": "points" if i % 2 else "statement", "part": "idea", "items": [], "narration": "words"} for i in range(6)]
        self.assertTrue(any("only words" in p for p in storyboard_problems(wordy, self.SPEC)))
        mixed = wordy[:1] + [{"layout": "diagram", "part": "idea", "nodes": ["A", "B"], "narration": "a b"}] * 3 + [wordy[1]]
        self.assertFalse(any("only words" in p for p in storyboard_problems(mixed, self.SPEC)))

    SPEC = {"format": "long", "wps": 2.5, "target_seconds": 240, "max_words": 600}

    def test_one_picture_for_forty_seconds_is_sent_back(self):
        from postcrew.checks import storyboard_problems
        long = [{"layout": "diagram", "part": "idea", "nodes": ["Client", "Server"], "narration": "The client calls the server. " + "word " * 120}]
        self.assertTrue(any("split it" in p for p in storyboard_problems(long, self.SPEC)))

    def test_every_box_and_point_must_be_said(self):
        from postcrew.checks import storyboard_problems
        ok = [{"layout": "diagram", "nodes": ["Client", "API Gateway|gateway"], "narration": "The client calls the gateway."}]
        self.assertEqual(storyboard_problems(ok, self.SPEC), [])
        bad = [{"layout": "diagram", "nodes": ["Redis Cache", "Message Queue"], "narration": "The client calls the server."}]
        self.assertTrue(any("never says it" in p for p in storyboard_problems(bad, self.SPEC)))
        pts = [{"layout": "points", "items": ["Ask the questions"], "narration": "Begin with requirements."}]
        self.assertTrue(any("never says it" in p for p in storyboard_problems(pts, self.SPEC)))
        grow = [{"layout": "diagram", "nodes": ["Client", "Server"], "narration": "The client calls the server."},
                {"layout": "diagram", "nodes": ["Client", "Server", "Cache"], "narration": "Then it reaches the cache."}]
        self.assertEqual(storyboard_problems(grow, self.SPEC), [])   # boxes already drawn need not be named again

    def test_three_plain_scenes_in_a_row_are_sent_back(self):
        from postcrew.checks import storyboard_problems
        row = [{"layout": "statement", "narration": "One."}] * 3
        self.assertTrue(any("in a row" in p for p in storyboard_problems(row, self.SPEC)))


class TeachingVoiceTests(unittest.TestCase):
    SPEC = {"format": "long", "wps": 2.5}

    def sc(self, *texts):
        return [{"narration": t, "part": "idea", "layout": "statement"} for t in texts]

    def test_notes_read_aloud_are_sent_back(self):
        from postcrew.checks import teaching_problems
        notes = self.sc("Round robin takes turns.", "Use it when times vary.", "Least connections adapts.", "Health checks help.", "Layer 7 sees requests.", "Done.")
        text = " ".join(teaching_problems(notes, self.SPEC))
        self.assertIn("clipped fragments", text)
        self.assertIn("never speaks to the student", text)
        self.assertIn("one real question", text)
        self.assertIn("no example", text)

    def test_a_professor_passes(self):
        from postcrew.checks import teaching_problems
        prof = self.sc("Have you ever wondered how a busy website stays up when a million people open it at once?",
                       "Imagine a pizza shop with three chefs, and one person at the counter who hands every order to a chef.",
                       "Let's call that person the load balancer, and we will see why the choice of chef matters.",
                       "So, in short, the counter person only decides who gets the next order. Does that make sense?")
        self.assertEqual(teaching_problems(prof, self.SPEC), [])

    def test_semicolons_and_colons_are_sent_back(self):
        from postcrew.checks import teaching_problems
        prof = self.sc("Have you ever wondered how a busy website stays up when a million people open it at once?",
                       "Imagine a pizza shop with three chefs; one person hands every order to a chef.",
                       "Let's call that person the load balancer and see why the choice matters to us.",
                       "So, in short, there are two ways: turns, or the least busy chef. Does that make sense?")
        text = " ".join(teaching_problems(prof, self.SPEC))
        self.assertIn("scene 2: no semicolons", text)
        self.assertIn("scene 4: no semicolons", text)


