"""LinkedIn: OAuth sign-in and the official Posts API (member posts with native image/video).

Needs a LinkedIn developer app with the products "Share on LinkedIn" and
"Sign In with LinkedIn using OpenID Connect" (scopes: openid profile w_member_social).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.linkedin.com"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
SCOPE = "openid profile w_member_social"
RESERVED = set("\\|{}@[]()<>*_~")


class LinkedInError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status

    @property
    def unauthorized(self):
        return self.status in (401, 403)


def escape_commentary(text):
    """LinkedIn's post text format treats these characters as markup; an unescaped '(' can cut a post short.
    '#' is left alone so hashtags still work."""
    return "".join("\\" + c if c in RESERVED else c for c in text)


def authorize_url(client_id, redirect_uri, state, extra_scopes=()):
    """extra_scopes: permissions of other LinkedIn products on your app (engage.scopes: the Community Management API's, so the crew can
    read and answer the comments on your posts)."""
    scope = " ".join(dict.fromkeys(SCOPE.split() + [x for x in extra_scopes if x]))
    return AUTH_URL + "?" + urllib.parse.urlencode({"response_type": "code", "client_id": client_id,
                                                    "redirect_uri": redirect_uri, "state": state, "scope": scope})


def exchange_code(client_id, client_secret, code, redirect_uri, opener=urllib.request.urlopen):
    data = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                   "client_id": client_id, "client_secret": client_secret}).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(req, timeout=30) as r:
            return json.load(r)  # {"access_token", "expires_in", ...}
    except urllib.error.HTTPError as e:
        raise LinkedInError(f"token exchange failed: HTTP {e.code} {e.read().decode(errors='replace')[:300]}", e.code)


class LinkedIn:
    def __init__(self, token, version="202601", opener=urllib.request.urlopen, sleep=time.sleep):
        self.token, self.version, self.opener, self.sleep = token, version, opener, sleep

    def request(self, method, url, *, headers=None, body=None, raw=False, auth=True, versioned=True):
        h = {"Authorization": f"Bearer {self.token}"} if auth else {}
        if not raw:
            h.update({"X-Restli-Protocol-Version": "2.0.0"})
            if versioned:
                h["LinkedIn-Version"] = self.version
        h.update({k: v for k, v in (headers or {}).items() if v != ""})
        data = None
        if body is not None:
            if isinstance(body, (bytes, bytearray)):
                data = body
            else:
                data = json.dumps(body).encode()
                h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with self.opener(req, timeout=300) as r:
                payload = r.read()
                return r.status, dict(r.headers), (json.loads(payload) if payload and not raw else payload)
        except urllib.error.HTTPError as e:
            raise LinkedInError(f"HTTP {e.code} from {method} {url.split('?')[0]}: "
                                f"{e.read().decode(errors='replace')[:400]}", e.code)
        except urllib.error.URLError as e:
            raise LinkedInError(f"network error calling LinkedIn: {e.reason}")

    def userinfo(self):
        return self.request("GET", f"{API}/v2/userinfo")[2]  # {"sub", "name", ...}

    def person_urn(self):
        return f"urn:li:person:{self.userinfo()['sub']}"

    def upload_image(self, owner, path):
        _, _, r = self.request("POST", f"{API}/rest/images?action=initializeUpload",
                               body={"initializeUploadRequest": {"owner": owner}})
        v = r["value"]
        self.request("PUT", v["uploadUrl"], body=Path(path).read_bytes(),
                     headers={"Content-Type": "application/octet-stream"}, raw=True)
        return v["image"]

    def upload_video(self, owner, path, log=print):
        data = Path(path).read_bytes()
        _, _, r = self.request("POST", f"{API}/rest/videos?action=initializeUpload", body={
            "initializeUploadRequest": {"owner": owner, "fileSizeBytes": len(data),
                                        "uploadCaptions": False, "uploadThumbnail": False}})
        v = r["value"]
        etags = []
        for part in v["uploadInstructions"]:  # pre-signed URLs: no Authorization header
            _, hdrs, _ = self.request("PUT", part["uploadUrl"], body=data[part["firstByte"]: part["lastByte"] + 1],
                                      headers={"Content-Type": "application/octet-stream"}, raw=True, auth=False)
            etags.append((hdrs.get("ETag") or hdrs.get("etag") or "").strip('"'))
        self.request("POST", f"{API}/rest/videos?action=finalizeUpload", body={
            "finalizeUploadRequest": {"video": v["video"], "uploadToken": v.get("uploadToken", ""),
                                      "uploadedPartIds": etags}})
        urn = v["video"]
        for _ in range(60):  # wait up to ~5 min for processing
            _, _, st = self.request("GET", f"{API}/rest/videos/{urllib.parse.quote(urn, safe='')}")
            log(f"video status: {st.get('status')}")
            if st.get("status") == "AVAILABLE":
                return urn
            if st.get("status") in ("PROCESSING_FAILED", "FAILED"):
                raise LinkedInError("LinkedIn failed to process the video")
            self.sleep(5)
        raise LinkedInError("timed out waiting for LinkedIn to process the video")

    def create_post(self, owner, text, media_urn=None, title=""):
        body = {"author": owner, "commentary": escape_commentary(text), "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                                 "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
        if media_urn:
            body["content"] = {"media": {"title": title[:200], "id": media_urn}}
        _, headers, _ = self.request("POST", f"{API}/rest/posts", body=body)
        return headers.get("x-restli-id") or headers.get("X-RestLi-Id")

    # ---------- comments ----------
    # LinkedIn's versioned /rest/socialActions needs a partner product (Community Management API); the older /v2/socialActions accepts
    # what "Share on LinkedIn" (w_member_social) grants. Each call tries the versioned one, then the older one when refused.
    def social(self, method, urn, suffix="", body=None, query=""):
        path = f"socialActions/{urllib.parse.quote(urn, safe='')}{suffix}{query}"
        try:
            return self.request(method, f"{API}/rest/{path}", body=body)
        except LinkedInError as e:
            if e.status not in (401, 403, 404, 426):
                raise
            first = e
        try:
            return self.request(method, f"{API}/v2/{path}", body=body, headers={"LinkedIn-Version": ""}, versioned=False)
        except LinkedInError as e:
            if e.status in (401, 403) and first.status in (401, 403):
                raise LinkedInError(f"{e} (the versioned API said: {first})", e.status)
            raise

    def add_comment(self, owner, post_urn, text, parent=None):
        """A comment on a post, or (parent: a comment's URN) a reply to that comment. Returns the new comment's URN when LinkedIn says."""
        body = {"actor": owner, "object": post_urn, "message": {"text": text}}
        if parent:
            body["parentComment"] = parent
        _, headers, data = self.social("POST", parent or post_urn, "/comments", body=body)
        data = data if isinstance(data, dict) else {}
        return headers.get("x-restli-id") or headers.get("X-RestLi-Id") or data.get("$URN") or data.get("commentUrn")

    def comments(self, urn, count=50):
        """The comments on a post (or the replies to a comment): [{urn, id, actor, text, created, parent}], oldest first."""
        _, _, data = self.social("GET", urn, "/comments", query=f"?count={count}")
        out = []
        for c in (data or {}).get("elements") or []:
            cid = c.get("id") or ""
            curn = c.get("$URN") or c.get("commentUrn") or (f"urn:li:comment:({urn},{cid})" if cid else "")
            out.append({"urn": curn, "id": cid, "actor": c.get("actor") or (c.get("created") or {}).get("actor", ""),
                        "text": ((c.get("message") or {}).get("text") or "").strip(), "created": (c.get("created") or {}).get("time"),
                        "parent": c.get("parentComment"), "replies": ((c.get("commentsSummary") or {}).get("aggregatedTotalComments")
                                                                      or (c.get("commentsSummary") or {}).get("totalFirstLevelComments") or 0)})
        return sorted(out, key=lambda c: c.get("created") or 0)
