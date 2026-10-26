"""YouTube Data API v3: OAuth sign-in, channel lookup, resumable video upload and thumbnails.

Standard library only. Tokens and secrets never appear in error messages.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
CHUNK = 8 * 1024 * 1024
QUOTA_REASONS = ("quotaexceeded", "dailylimitexceeded", "uploadlimitexceeded", "ratelimitexceeded")
RECONNECT = "reconnect YouTube in Credentials"
sleep = time.sleep  # tests replace this


class YouTubeError(RuntimeError):
    def __init__(self, message, kind="failed", status=None):
        super().__init__(message)
        self.kind, self.status = kind, status


def _parse(raw):
    try:
        d = json.loads(raw.decode(errors="replace") if isinstance(raw, (bytes, bytearray)) else raw)
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _map_error(code, raw):
    d = _parse(raw)
    err = d.get("error")
    if isinstance(err, dict):
        msg = err.get("message", "")
        reasons = " ".join(str(x.get("reason", "")) for x in err.get("errors", []) if isinstance(x, dict)).lower()
        grant = ""
    else:
        grant = str(err or "")
        msg = d.get("error_description") or grant
        reasons = ""
    msg = str(msg)[:300] or (raw.decode(errors="replace")[:200] if raw else "")
    if grant == "invalid_grant" or code == 401:
        return YouTubeError(f"YouTube sign-in is no longer valid: {RECONNECT}", "auth", code)
    if code == 403 and any(r in reasons for r in QUOTA_REASONS):
        return YouTubeError(f"YouTube quota or upload limit reached: {msg}", "quota", code)
    if code == 403 or grant in ("invalid_client", "unauthorized_client", "access_denied"):
        return YouTubeError(f"YouTube refused access ({msg}): {RECONNECT}", "auth", code)
    if code == 429:
        return YouTubeError(f"YouTube is rate limiting requests: {msg}", "quota", code)
    if code in (400, 404, 422):
        return YouTubeError(f"YouTube rejected the request: {msg}", "invalid", code)
    return YouTubeError(f"YouTube HTTP {code}: {msg}", "failed", code)


def _raw(opener, method, url, headers=None, data=None, timeout=300):
    """One request. Returns (status, headers, body bytes); a 308 (resume incomplete) is returned, not raised."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with opener(req, timeout=timeout) as r:
            return getattr(r, "status", 200), r.headers, r.read()
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        if e.code == 308:
            return 308, e.headers, raw
        raise _map_error(e.code, raw)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise YouTubeError(f"could not reach YouTube: {getattr(e, 'reason', e)}", "network")


def _send(opener, method, url, headers=None, data=None, tries=3, timeout=120):
    for i in range(tries):
        try:
            return _raw(opener, method, url, headers, data, timeout)
        except YouTubeError as e:
            if i < tries - 1 and (e.kind == "network" or e.status in (429, 500, 502, 503, 504)):
                sleep(2 * (i + 1))
                continue
            raise


def auth_url(client_id, redirect_uri, state):
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state})


def _token_request(opener, form):
    data = urllib.parse.urlencode(form).encode()
    _, _, body = _send(opener, "POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, data, timeout=30)
    d = _parse(body)
    if not d.get("access_token"):
        raise YouTubeError(f"Google did not return an access token: {RECONNECT}", "auth")
    return d


def exchange_code(client_id, client_secret, code, redirect_uri, opener=None):
    d = _token_request(opener or urllib.request.urlopen, {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": client_id, "client_secret": client_secret})
    return {"refresh_token": d.get("refresh_token", ""), "access_token": d["access_token"],
            "expires_in": int(d.get("expires_in", 3600))}


class YouTube:
    def __init__(self, client_id, client_secret, refresh_token, opener=None):
        self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
        self.opener = opener or urllib.request.urlopen
        self.clock = time.time
        self._access, self._expires = None, 0.0

    def token(self):
        if not self._access or self.clock() >= self._expires - 60:
            d = _token_request(self.opener, {"grant_type": "refresh_token", "refresh_token": self.refresh_token,
                                             "client_id": self.client_id, "client_secret": self.client_secret})
            self._access, self._expires = d["access_token"], self.clock() + int(d.get("expires_in", 3600))
        return self._access

    def _auth(self, extra=None):
        return {"Authorization": f"Bearer {self.token()}", **(extra or {})}

    def channel(self):
        _, _, body = _send(self.opener, "GET", f"{API}/channels?part=snippet&mine=true", self._auth(), timeout=30)
        items = _parse(body).get("items") or []
        if not items:
            raise YouTubeError("this Google account has no YouTube channel", "invalid")
        return {"id": items[0].get("id", ""), "title": (items[0].get("snippet") or {}).get("title", "")}

    def upload(self, path, title, description, tags, category_id="28", privacy="private", publish_at=None,
               made_for_kids=False, progress=None):
        total = os.path.getsize(path)
        if total <= 0:
            raise YouTubeError("the video file is empty", "invalid")
        status = {"privacyStatus": "private" if publish_at else privacy, "selfDeclaredMadeForKids": bool(made_for_kids)}
        if publish_at:
            status["publishAt"] = publish_at
        meta = {"snippet": {"title": title, "description": description, "tags": list(tags or []),
                            "categoryId": str(category_id)}, "status": status}
        _, hdrs, _ = _send(self.opener, "POST", f"{UPLOAD_API}/videos?uploadType=resumable&part=snippet,status",
                           self._auth({"Content-Type": "application/json; charset=UTF-8",
                                       "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(total)}),
                           json.dumps(meta).encode(), timeout=60)
        session = hdrs.get("Location") if hdrs else None
        if not session:
            raise YouTubeError("YouTube did not start an upload session", "failed")
        result = self._send_file(session, path, total, progress)
        vid = result.get("id")
        if not vid:
            raise YouTubeError("YouTube finished the upload but returned no video id", "failed")
        return {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}"}

    @staticmethod
    def _offset(hdrs):
        rng = (hdrs.get("Range") if hdrs else None) or ""
        return int(rng.rsplit("-", 1)[1]) + 1 if "-" in rng else 0

    def _send_file(self, session, path, total, progress):
        offset, fails = 0, 0
        with open(path, "rb") as f:
            while True:
                f.seek(offset)
                chunk = f.read(CHUNK)
                hdr = {"Content-Type": "video/mp4", "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{total}"}
                try:
                    code, hdrs, body = _raw(self.opener, "PUT", session, hdr, chunk)
                    fails = 0
                except YouTubeError as e:
                    if e.kind != "network" and e.status not in (500, 502, 503, 504):
                        raise
                    fails += 1
                    if fails > 3:
                        raise
                    sleep(2 * fails)
                    # ask where the server got to, then carry on from there
                    code, hdrs, body = self._status(session, total)
                if code == 308:
                    offset = self._offset(hdrs)
                    if progress:
                        progress(offset, total)
                    continue
                if progress:
                    progress(total, total)
                return _parse(body)

    def _status(self, session, total):
        for i in range(3):
            try:
                return _raw(self.opener, "PUT", session, {"Content-Range": f"bytes */{total}", "Content-Length": "0"}, b"")
            except YouTubeError as e:
                if e.kind != "network" or i == 2:
                    raise
                sleep(2 * (i + 1))

    def set_thumbnail(self, video_id, image_path):
        ctype = "image/jpeg" if str(image_path).lower().endswith((".jpg", ".jpeg")) else "image/png"
        with open(image_path, "rb") as f:
            data = f.read()
        _send(self.opener, "POST", f"{UPLOAD_API}/thumbnails/set?videoId={urllib.parse.quote(video_id)}",
              self._auth({"Content-Type": ctype}), data, timeout=60)
