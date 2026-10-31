"""The Studio's YouTube endpoints over real HTTP: credentials, voices, the owner's own files, plan days, queue edits, video playback."""
import json
import shutil
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from helpers import TempWorkspace
from postcrew import crew, voice
from postcrew.studio.server import Studio, make_handler

DAY = "2026-11-03"


class YouTubeStudioTests(unittest.TestCase):
    def setUp(self):
        self.tw = TempWorkspace()
        self.ws = self.tw.__enter__()
        self.studio = Studio(self.ws, 0)
        handler = make_handler(self.studio)
        handler.log_message = lambda *a: None
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.studio.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.studio.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        cfg = self.ws.config()
        cfg["platforms"]["youtube"]["enabled"] = True
        self.ws.save_config(cfg)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tw.__exit__()

    def req(self, method, path, body=None, raw=None, headers=None):
        h = {"Content-Type": "application/octet-stream" if raw is not None else "application/json", "X-Postcrew": "1"}
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read() or b"{}"), resp.headers
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}"), e.headers

    # ---------- starting a run ----------
    def test_a_run_for_a_day_with_no_post_says_why_instead_of_silently_doing_nothing(self):
        code, d, _ = self.req("POST", "/api/runs", {"platform": "youtube", "date": "2026-11-04"})   # a Wednesday
        self.assertEqual(code, 400)
        self.assertIn("nothing is scheduled for YouTube on Wednesday 2026-11-04", d["error"])
        self.assertIn("Choose a topic", d["error"])
        code, d, _ = self.req("POST", "/api/runs", {"platform": "youtube", "date": "2026-11-04", "category": "nope"})
        self.assertEqual(code, 400)
        self.assertIn("no topic 'nope'", d["error"])

    def test_a_chosen_topic_is_written_for_any_date_and_the_run_exists_before_the_answer(self):
        def fake(ws, day, category, **kw):
            d = ws.runs_dir / kw["run_id"]
            d.mkdir(parents=True)
            (d / "status.json").write_text("{}")
            return {"ok": True, "run_id": kw["run_id"]}
        with mock.patch.object(crew, "run_crew", side_effect=fake) as m:
            code, d, _ = self.req("POST", "/api/runs", {"platform": "youtube", "date": "2026-11-04", "category": "short-tip",
                                                       "dry_run": True})
        self.assertEqual(code, 200)
        self.assertTrue((self.ws.runs_dir / d["run_id"] / "status.json").exists())
        self.assertEqual(m.call_args.args[2], "short-tip")

    def test_a_run_the_crew_refuses_to_start_is_reported(self):
        refusal = {"ok": False, "reason": "another crew run is in progress", "run_id": None}
        with mock.patch.object(crew, "run_crew", return_value=refusal):
            code, d, _ = self.req("POST", "/api/runs", {"platform": "youtube", "date": DAY})
        self.assertEqual(code, 400)
        self.assertIn("another crew run is in progress", d["error"])

    def test_run_now_defaults_to_a_date_that_has_a_post(self):
        code, d, _ = self.req("GET", "/api/overview?platform=youtube")
        self.assertEqual(code, 200)
        from postcrew import platforms
        self.assertTrue(platforms.category_for(self.ws.config()["platforms"]["youtube"]["schedule"], d["next"]["run_for"]))

    # ---------- credentials ----------
    def test_credentials_are_write_only_and_checked(self):
        code, d, _ = self.req("PUT", "/api/credentials", {"youtube_client_id": "123-abc.apps.googleusercontent.com",
                                                          "youtube_client_secret": "shh", "elevenlabs_api_key": "xi-1"})
        self.assertEqual(code, 200)
        sec = d["secrets"]
        self.assertEqual((sec["youtube_client_secret"], sec["elevenlabs_api_key"]), (True, True))   # never read back
        self.assertEqual(sec["youtube_client_id"], "123-abc.apps.googleusercontent.com")
        self.assertIn("/oauth/youtube/callback", d["youtube_redirect_uri"])
        self.assertEqual(self.req("PUT", "/api/credentials", {"youtube_client_id": "nope"})[0], 400)

    def test_connect_youtube_needs_the_app_first_then_redirects_to_google(self):
        code, body, _ = self.try_get("/oauth/youtube/start")
        self.assertIn(b"Cannot connect yet", body)           # a readable page, like LinkedIn's
        self.ws.update_secrets(youtube_client_id="123-abc.apps.googleusercontent.com", youtube_client_secret="shh")
        code, _, headers = self.try_get("/oauth/youtube/start")
        self.assertEqual(code, 302)
        self.assertTrue(headers["Location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
        self.assertIn("youtube.upload", headers["Location"])

    def try_get(self, path):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(self.base + path) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read(), e.headers

    def test_disconnect_youtube_keeps_the_app_settings(self):
        self.ws.update_secrets(youtube_client_id="123-abc.apps.googleusercontent.com", youtube_refresh_token="rt",
                               youtube_channel_title="Mine")
        self.assertEqual(self.req("POST", "/api/credentials/disconnect", {"app": "youtube"})[0], 200)
        s = self.ws.secrets()
        self.assertNotIn("youtube_refresh_token", s)
        self.assertIn("youtube_client_id", s)

    # ---------- voices ----------
    def test_voices_need_a_key_and_sample_is_cached_audio(self):
        self.assertEqual(self.req("GET", "/api/voices")[0], 400)
        self.ws.update_secrets(elevenlabs_api_key="xi-1")
        with mock.patch.object(voice, "list_voices", return_value=[{"id": "abcdefgh1", "name": "Rachel", "category": "premade",
                                                                    "preview_url": ""}]):
            code, d, _ = self.req("GET", "/api/voices")
        self.assertEqual((code, d["voices"][0]["name"]), (200, "Rachel"))
        with mock.patch.object(voice, "check_key", return_value={"ok": True, "message": "ok", "characters_left": 900}):
            self.assertEqual(self.req("POST", "/api/credentials/test-voice", {})[1]["characters_left"], 900)

        def fake(root, text, cfg, key, opener=None):
            p = self.ws.root / "cache" / "voice" / "x.mp3"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"ID3fake")
            return {"path": str(p), "seconds": 1.0, "characters": len(text)}
        with mock.patch.object(voice, "cached_synthesize", side_effect=fake):
            code, d, _ = self.req("POST", "/api/voices/sample", {"voice_id": "abcdefgh1"})
            self.assertEqual(code, 200)
            self.assertEqual(self.req("POST", "/api/voices/sample", {"voice_id": "../etc"})[0], 400)
        r = urllib.request.urlopen(self.base + d["url"])
        self.assertEqual(r.read(), b"ID3fake")

    # ---------- the owner's own files ----------
    def test_upload_list_and_remove_a_script(self):
        body = ("title: Why JWTs leak\n\nYour token can leak from a log. Most teams log every header.\n\n"
                "Strip it first. Then log a hash.\n\nCheck the logs again.\n").encode()
        code, d, _ = self.req("POST", f"/api/assets/youtube/{DAY}?kind=script&name=my%20script.md", raw=body)
        self.assertEqual(code, 200, d)
        a = d["assets"]["script"]
        self.assertEqual((a["name"], len(a["scenes"])), ("my script.md", 3))
        self.assertTrue(all("label" in c and "ok" in c for c in a["checks"]))
        self.assertEqual(self.req("GET", f"/api/assets/youtube/{DAY}")[1]["assets"]["script"]["name"], "my script.md")
        code, d, _ = self.req("POST", f"/api/assets/youtube/{DAY}/remove", {"kind": "script"})
        self.assertEqual((code, d["assets"]), (200, {}))

    def test_bad_uploads_are_refused_with_a_reason(self):
        code, d, _ = self.req("POST", f"/api/assets/youtube/{DAY}?kind=voice&name=a.exe", raw=b"x")
        self.assertEqual(code, 400)
        self.assertIn(".mp3", d["error"])
        self.assertEqual(self.req("POST", f"/api/assets/youtube/{DAY}?kind=script&name=a.txt", raw=b"")[0], 400)
        self.assertEqual(self.req("POST", f"/api/assets/youtube/{DAY}?kind=nope&name=a.txt", raw=b"x")[0], 400)
        code, d, _ = self.req("POST", f"/api/assets/youtube/{DAY}?kind=script&name=a.txt", raw=b"no scene breaks here" * 0 + b"   ")
        self.assertEqual(code, 200)       # stored; the listing reports that it cannot be read
        self.assertFalse(d["assets"]["script"]["checks"][-1]["ok"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_a_video_is_probed_and_checked_against_the_format(self):
        mp4 = self.ws.root / "t.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=2", "-f", "lavfi",
                        "-i", "sine=duration=2", "-shortest", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        code, d, _ = self.req("POST", f"/api/assets/youtube/{DAY}?kind=video&name=t.mp4", raw=mp4.read_bytes())
        self.assertEqual(code, 200, d)
        v = d["assets"]["video"]
        self.assertEqual((v["width"], v["height"]), (1920, 1080))
        self.assertTrue(v["thumbnail"].startswith("/media/"))
        self.assertTrue(any(not c["ok"] for c in v["checks"]))      # landscape is not a Short (the default)
        self.assertEqual(urllib.request.urlopen(self.base + v["thumbnail"]).status, 200)

    # ---------- plan, run options, queue ----------
    def test_a_plan_day_can_carry_its_own_video_format(self):
        import datetime
        from postcrew.agents import planner
        from postcrew.crew import local_now
        from helpers import ScriptedLLM
        from unittest import mock
        cfg = self.ws.config()
        cfg["platforms"]["youtube"]["topics"] = ["Hash maps"]
        self.ws.save_config(cfg)
        plans = [{"title": t, "angle": "buckets", "context": "c", "example": "e", "takeaway": "t",
                  "search_queries": ["q"]} for t in ['Open addressing vs chaining', 'Resizing without pauses', 'Choosing a hash function', 'Collision attacks', 'Load factor tuning', 'Hash maps in databases', 'Iteration order surprises', 'Concurrent hash maps', 'Memory cost of buckets', 'Perfect hashing for fixed keys']]
        with mock.patch("postcrew.llm.make_backend", return_value=ScriptedLLM({"planner": [{"plans": plans}]})):
            code, d, _ = self.req("POST", "/api/plan/generate", {"platform": "youtube"})
        self.assertEqual((code, d["added"]), (200, 10), d)
        day = (local_now(self.ws.config()).date() + datetime.timedelta(days=1)).isoformat()
        a, b = d["items"][:2]
        code, d, _ = self.req("POST", "/api/plan/assign", {"platform": "youtube", "id": a["id"], "date": day, "format": "long"})
        self.assertEqual(code, 200, d)
        self.assertEqual(d["days"][day][0]["format"], "long")
        entry = planner.load_plan(self.ws, "youtube")[day]
        self.assertEqual((entry["format"], entry["category"]), ("long", "assigned-long"))
        self.assertEqual(self.req("POST", "/api/plan/assign", {"platform": "youtube", "id": b["id"], "date": day, "format": "huge"})[0], 400)
        code, d, _ = self.req("POST", "/api/plan/assign", {"platform": "youtube", "id": a["id"], "date": day, "format": "short"})   # change it
        self.assertEqual(d["days"][day][0]["format"], "short")

    def queue_video(self):
        media = self.ws.root / "media"
        media.mkdir(exist_ok=True)
        (media / "v.mp4").write_bytes(bytes(range(256)) * 40)
        self.ws.save_queue([{"id": "yt1", "platform": "youtube", "date": DAY, "status": "awaiting_approval", "topic": "Old title here",
                             "text": "d", "media": "media/v.mp4", "media_kind": "video", "scheduled_at": "2026-11-03T23:00:00+00:00",
                             "youtube": {"title": "Old title here", "description": "old", "tags": ["a", "b", "c"], "format": "short",
                                         "seconds": 40, "scenes": []}}])

    def test_a_queued_video_can_be_edited_and_played_with_seeking(self):
        self.queue_video()
        code, d, _ = self.req("POST", "/api/queue/yt1/edit", {"title": "A better title", "description": "new text",
                                                              "tags": "x, y, z"})
        self.assertEqual(code, 200, d)
        self.assertEqual((d["topic"], d["youtube"]["tags"]), ("A better title", ["x", "y", "z"]))
        self.assertEqual(self.req("POST", "/api/queue/yt1/edit", {"title": "no"})[0], 400)
        r = urllib.request.urlopen(urllib.request.Request(self.base + "/media/v.mp4", headers={"Range": "bytes=10-19"}))
        self.assertEqual((r.status, r.headers["Content-Range"], r.read()), (206, "bytes 10-19/10240", bytes(range(10, 20))))
        self.assertEqual(urllib.request.urlopen(self.base + "/media/v.mp4").headers["Accept-Ranges"], "bytes")

    def test_publish_now_goes_through_the_youtube_client_in_practice_mode(self):
        self.queue_video()
        code, d, _ = self.req("POST", "/api/queue/yt1/publish_now", {})
        self.assertEqual((code, d["status"]), (200, "dry_run"))


if __name__ == "__main__":
    unittest.main()
