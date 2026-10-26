"""YouTube client against a fake HTTP opener: OAuth, token caching, the resumable upload, errors. No network."""
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

from postcrew import youtube
from postcrew.youtube import YouTube, YouTubeError


class Headers(dict):
    def __getitem__(self, k):
        v = self.get(k)
        if v is None:
            raise KeyError(k)
        return v

    def get(self, k, default=None):
        for key, v in self.items():
            if key.lower() == k.lower():
                return v
        return default


class Resp(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode())
        self.status, self.headers = status, Headers(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def err(code, body=None, headers=None):
    return ("err", code, body if isinstance(body, bytes) else json.dumps(body or {}).encode(), headers or {})


class FakeHTTP:
    """Answers in order (the last repeats). Resp -> returned; err(...) -> HTTPError; Exception -> raised."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, req, timeout=None):
        self.requests.append({"url": req.full_url, "method": req.get_method(), "data": req.data,
                              "headers": Headers({k: v for k, v in req.header_items()})})
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        if isinstance(a, tuple):
            raise urllib.error.HTTPError(req.full_url, a[1], "err", Headers(a[3]), io.BytesIO(a[2]))
        return a


def tok():
    return Resp({"access_token": "AT", "expires_in": 3600})

SESSION = "https://upload.example/session/1"


class YouTubeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for mod, name, val in ((youtube, "sleep", lambda s: None), (youtube, "CHUNK", 10)):
            old = getattr(mod, name)
            setattr(mod, name, val)
            self.addCleanup(setattr, mod, name, old)

    def video(self, size=25):
        p = self.dir / "v.mp4"
        p.write_bytes(bytes(range(size)))
        return str(p)

    def client(self, *answers):
        http = FakeHTTP(*answers)
        return YouTube("cid", "csecret", "RT", http), http

    def test_auth_url(self):
        u = urllib.parse.urlparse(youtube.auth_url("cid", "http://localhost/cb", "st"))
        q = urllib.parse.parse_qs(u.query)
        self.assertEqual(u.netloc + u.path, "accounts.google.com/o/oauth2/v2/auth")
        self.assertEqual(q["scope"], ["https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"])
        self.assertEqual((q["access_type"], q["prompt"], q["response_type"], q["state"]),
                         (["offline"], ["consent"], ["code"], ["st"]))

    def test_exchange_code(self):
        http = FakeHTTP(Resp({"access_token": "AT", "refresh_token": "RT", "expires_in": 3599}))
        r = youtube.exchange_code("cid", "csecret", "the-code", "http://localhost/cb", http)
        self.assertEqual(r, {"refresh_token": "RT", "access_token": "AT", "expires_in": 3599})
        q = http.requests[0]
        self.assertEqual(q["url"], "https://oauth2.googleapis.com/token")
        self.assertEqual(q["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        form = urllib.parse.parse_qs(q["data"].decode())
        self.assertEqual(form["grant_type"], ["authorization_code"])
        self.assertEqual(form["code"], ["the-code"])
        self.assertEqual(form["client_secret"], ["csecret"])

    def test_access_token_is_cached_until_near_expiry(self):
        yt, http = self.client(Resp({"access_token": "A1", "expires_in": 3600}), Resp({"access_token": "A2", "expires_in": 3600}))
        now = [1000.0]
        yt.clock = lambda: now[0]
        self.assertEqual(yt.token(), "A1")
        now[0] += 3000
        self.assertEqual(yt.token(), "A1")
        self.assertEqual(len(http.requests), 1)
        now[0] += 545  # 3545 s: within 60 s of expiry
        self.assertEqual(yt.token(), "A2")
        form = urllib.parse.parse_qs(http.requests[1]["data"].decode())
        self.assertEqual((form["grant_type"], form["refresh_token"]), (["refresh_token"], ["RT"]))

    def test_channel(self):
        yt, http = self.client(tok(), Resp({"items": [{"id": "UC1", "snippet": {"title": "My Channel"}}]}))
        self.assertEqual(yt.channel(), {"id": "UC1", "title": "My Channel"})
        q = http.requests[1]
        self.assertEqual(q["url"], "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true")
        self.assertEqual(q["headers"]["Authorization"], "Bearer AT")

    def test_upload_start_request_and_chunks(self):
        path = self.video(25)
        seen = []
        yt, http = self.client(tok(), Resp(b"", headers={"Location": SESSION}),
                               err(308, headers={"Range": "bytes=0-9"}), err(308, headers={"Range": "bytes=0-19"}),
                               Resp({"id": "abc123"}))
        r = yt.upload(path, "T", "D", ["a", "b"], progress=lambda s, t: seen.append((s, t)))
        self.assertEqual(r, {"id": "abc123", "url": "https://www.youtube.com/watch?v=abc123"})
        start = http.requests[1]
        self.assertEqual(start["url"], "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status")
        self.assertEqual(start["headers"]["Authorization"], "Bearer AT")
        self.assertEqual(start["headers"]["X-Upload-Content-Type"], "video/mp4")
        self.assertEqual(start["headers"]["X-Upload-Content-Length"], "25")
        self.assertEqual(json.loads(start["data"]), {
            "snippet": {"title": "T", "description": "D", "tags": ["a", "b"], "categoryId": "28"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}})
        puts = http.requests[2:]
        self.assertEqual([p["headers"]["Content-Range"] for p in puts], ["bytes 0-9/25", "bytes 10-19/25", "bytes 20-24/25"])
        self.assertTrue(all(p["method"] == "PUT" and p["url"] == SESSION for p in puts))
        self.assertEqual(b"".join(p["data"] for p in puts), bytes(range(25)))
        self.assertEqual(seen, [(10, 25), (20, 25), (25, 25)])

    def test_308_resume_uses_servers_offset(self):
        path = self.video(25)
        # server only kept 0-4 of the first chunk: next chunk must start at 5
        yt, http = self.client(tok(), Resp(b"", headers={"Location": SESSION}),
                               err(308, headers={"Range": "bytes=0-4"}), Resp({"id": "v"}))
        yt.upload(path, "T", "D", [])
        self.assertEqual(http.requests[3]["headers"]["Content-Range"], "bytes 5-14/25")

    def test_failed_chunk_is_retried_after_asking_the_server(self):
        path = self.video(15)
        yt, http = self.client(tok(), Resp(b"", headers={"Location": SESSION}),
                               urllib.error.URLError("reset"),               # chunk 1 fails
                               err(308, headers={"Range": "bytes=0-9"}),      # status query: server has it all
                               Resp({"id": "vid"}))
        r = yt.upload(path, "T", "D", [])
        self.assertEqual(r["id"], "vid")
        status = http.requests[3]
        self.assertEqual(status["headers"]["Content-Range"], "bytes */15")
        self.assertEqual(status["data"], b"")
        self.assertEqual(http.requests[4]["headers"]["Content-Range"], "bytes 10-14/15")

    def test_chunk_gives_up_after_three_failures(self):
        path = self.video(15)
        yt, http = self.client(tok(), Resp(b"", headers={"Location": SESSION}), err(503, {}),
                               err(308), err(503, {}), err(308), err(503, {}), err(308), err(503, {}))
        with self.assertRaises(YouTubeError) as cm:
            yt.upload(path, "T", "D", [])
        self.assertEqual(cm.exception.status, 503)

    def test_publish_at_forces_private(self):
        yt, http = self.client(tok(), Resp(b"", headers={"Location": SESSION}), Resp({"id": "v"}))
        yt.upload(self.video(5), "T", "D", [], privacy="public", publish_at="2026-11-03T09:00:00Z", made_for_kids=True)
        st = json.loads(http.requests[1]["data"])["status"]
        self.assertEqual(st, {"privacyStatus": "private", "selfDeclaredMadeForKids": True, "publishAt": "2026-11-03T09:00:00Z"})

    def test_public_upload_has_no_publish_at(self):
        yt, http = self.client(tok(), Resp(b"", headers={"Location": SESSION}), Resp({"id": "v"}))
        yt.upload(self.video(5), "T", "D", [], privacy="public")
        st = json.loads(http.requests[1]["data"])["status"]
        self.assertEqual(st["privacyStatus"], "public")
        self.assertNotIn("publishAt", st)

    def test_set_thumbnail(self):
        img = self.dir / "t.png"
        img.write_bytes(b"\x89PNG")
        yt, http = self.client(tok(), Resp({}), Resp({}))
        yt.set_thumbnail("vid 1", str(img))
        q = http.requests[1]
        self.assertEqual(q["url"], "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId=vid%201")
        self.assertEqual((q["headers"]["Content-Type"], q["data"]), ("image/png", b"\x89PNG"))
        jpg = self.dir / "t.jpg"
        jpg.write_bytes(b"jpg")
        yt.set_thumbnail("v", str(jpg))
        self.assertEqual(http.requests[2]["headers"]["Content-Type"], "image/jpeg")

    def test_error_mapping(self):
        quota = {"error": {"code": 403, "message": "Quota hit", "errors": [{"reason": "quotaExceeded"}]}}
        cases = [(err(401, {"error": {"message": "x"}}), "auth", "reconnect YouTube in Credentials"),
                 (err(400, {"error": "invalid_grant", "error_description": "Token revoked"}), "auth", "reconnect YouTube"),
                 (err(403, quota), "quota", "Quota hit"),
                 (err(403, {"error": {"message": "m", "errors": [{"reason": "uploadLimitExceeded"}]}}), "quota", ""),
                 (err(403, {"error": {"message": "forbidden", "errors": [{"reason": "forbidden"}]}}), "auth", ""),
                 (err(400, {"error": {"message": "Bad title", "errors": [{"reason": "invalidTitle"}]}}), "invalid", "Bad title"),
                 (urllib.error.URLError("offline"), "network", "")]
        for answer, kind, text in cases:
            yt, _ = self.client(tok(), answer)
            with self.assertRaises(YouTubeError) as cm:
                yt.channel()
            self.assertEqual(cm.exception.kind, kind, answer)
            self.assertIn(text, str(cm.exception))
            for secret in ("AT", "RT", "csecret"):
                self.assertNotIn(f"Bearer {secret}", str(cm.exception))
            self.assertNotIn("csecret", str(cm.exception))

    def test_refresh_with_revoked_token_is_auth_error(self):
        yt, _ = self.client(err(400, {"error": "invalid_grant"}))
        with self.assertRaises(YouTubeError) as cm:
            yt.channel()
        self.assertEqual(cm.exception.kind, "auth")

    def test_retries_5xx_on_simple_calls(self):
        yt, http = self.client(tok(), err(503), Resp({"items": [{"id": "1", "snippet": {"title": "t"}}]}))
        self.assertEqual(yt.channel()["id"], "1")
        self.assertEqual(len(http.requests), 3)


if __name__ == "__main__":
    unittest.main()
