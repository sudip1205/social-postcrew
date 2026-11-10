"""Facebook Page Reels and Instagram Reels through Meta's Graph API (a port of the factory's pipeline/meta-publish.mjs).

Connection details: the Page id, Instagram user id and a Page access token. They come from the workspace secrets
(meta_page_id, meta_ig_user_id, meta_page_token) or, when those are empty, from the factory's secrets/meta.json
({"pageId", "igUserId", "pageAccessToken", "graphVersion"}), the same file meta-publish.mjs reads.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.facebook.com"
VERSION = "v23.0"


class MetaError(Exception):
    def __init__(self, msg, kind="platform"):
        super().__init__(msg)
        self.kind = kind   # auth | platform | media


def connection(ws):
    """{"page_id", "ig_user_id", "token", "version", "source"} or None when Meta is not set up."""
    s = ws.secrets()
    if s.get("meta_page_token") and s.get("meta_page_id"):
        return {"page_id": s["meta_page_id"], "ig_user_id": s.get("meta_ig_user_id"), "token": s["meta_page_token"],
                "version": s.get("meta_graph_version") or VERSION, "source": "Credentials"}
    from . import platforms
    from .agents.shorts import factory_dir
    f = factory_dir(platforms.view(ws.config(), "youtube")) / "secrets" / "meta.json"
    try:
        c = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    if not (c.get("pageAccessToken") and c.get("pageId")):
        return None
    return {"page_id": str(c["pageId"]), "ig_user_id": str(c.get("igUserId") or "") or None, "token": c["pageAccessToken"],
            "version": c.get("graphVersion") or VERSION, "source": str(f)}


class Meta:
    def __init__(self, page_id, ig_user_id, token, version=VERSION, sleep=time.sleep, timeout=120):
        self.page_id, self.ig_user_id, self.token, self.version = page_id, ig_user_id, token, version
        self.sleep, self.timeout = sleep, timeout

    def api(self, method, path, params=None, headers=None, body=None):
        url = path if path.startswith("http") else f"{GRAPH}/{self.version}/{path}"
        q = dict(params or {})
        if not path.startswith("http"):
            q["access_token"] = self.token
        if q:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, data=body if body is not None else (b"" if method == "POST" else None), method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout if body is None else 1800) as r:
                text = r.read().decode()
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            try:
                err = json.loads(text).get("error") or {}
            except ValueError:
                err = {"message": text[:300]}
            kind = "auth" if err.get("code") in (190, 102) else "platform"   # 190: the token expired or was revoked
            raise MetaError(f"{method} {e.code}: {err.get('error_user_msg') or err.get('message') or text[:300]}", kind) from None
        except urllib.error.URLError as e:
            raise MetaError(f"could not reach Meta: {e.reason}") from None
        try:
            return json.loads(text) if text.strip() else {}
        except ValueError:
            return {"raw": text}

    def check(self):
        page = self.api("GET", self.page_id, {"fields": "name,link"})
        ig = self.api("GET", self.ig_user_id, {"fields": "username,media_count"}) if self.ig_user_id else None
        return {"page": page.get("name"), "instagram": (ig or {}).get("username")}

    def facebook_reel(self, video, caption, log=print):
        data = Path(video).read_bytes()
        start = self.api("POST", f"{self.page_id}/video_reels", {"upload_phase": "start"})
        vid = start["video_id"]
        log(f"facebook: uploading {len(data) / 1e6:.1f} MB")
        self.api("POST", start["upload_url"], headers={"Authorization": f"OAuth {self.token}", "offset": "0",
                                                      "file_size": str(len(data))}, body=data)
        self.api("POST", f"{self.page_id}/video_reels", {"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                                         "description": caption})
        for _ in range(120):
            st = (self.api("GET", vid, {"fields": "status"}).get("status") or {})
            if st.get("video_status") == "ready":
                break
            if st.get("video_status") == "error":
                raise MetaError(f"Facebook could not process the video: {json.dumps(st)[:300]}", "media")
            self.sleep(5)
        return {"id": vid, "url": f"https://www.facebook.com/reel/{vid}"}

    def _ig_from_url(self, url, caption):
        return self.api("POST", f"{self.ig_user_id}/media", {"media_type": "REELS", "video_url": url, "caption": caption,
                                                             "share_to_feed": "true"})

    def instagram_reel(self, video, caption, facebook_id=None, log=print):
        """Resumable upload first; if Instagram refuses it, let it fetch the copy Facebook already hosts (as meta-publish.mjs)."""
        if not self.ig_user_id:
            raise MetaError("no Instagram account is linked (igUserId)", "auth")
        data = Path(video).read_bytes()
        try:
            c = self.api("POST", f"{self.ig_user_id}/media", {"media_type": "REELS", "upload_type": "resumable",
                                                              "caption": caption, "share_to_feed": "true"})
            log(f"instagram: uploading {len(data) / 1e6:.1f} MB")
            self.api("POST", c["uri"], headers={"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(len(data)),
                                                "Content-Type": "application/octet-stream"}, body=data)
        except (MetaError, KeyError) as e:
            src = facebook_id and self.api("GET", facebook_id, {"fields": "source"}).get("source")
            if not src:
                raise
            log(f"instagram: upload refused ({str(e)[:120]}); using the Facebook copy")
            c = self._ig_from_url(src, caption)
        for _ in range(120):
            s = self.api("GET", c["id"], {"fields": "status_code,status"})
            if s.get("status_code") == "FINISHED":
                break
            if s.get("status_code") in ("ERROR", "EXPIRED"):
                raise MetaError(f"Instagram could not process the video: {s.get('status')}", "media")
            self.sleep(5)
        pub = self.api("POST", f"{self.ig_user_id}/media_publish", {"creation_id": c["id"]})
        link = self.api("GET", pub["id"], {"fields": "permalink"}).get("permalink")
        return {"id": pub["id"], "url": link or ""}


def caption(title, description):
    """Title, the description's first paragraph, a 'Challenge:' paragraph if any, and its hashtags (meta-publish.mjs autoCaption),
    kept inside Instagram's limits (2200 characters, 30 hashtags)."""
    title = re.sub(r"\s*#shorts\s*$", "", title or "", flags=re.I).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", description or "") if p.strip()]
    text = [p for p in paras if not p.startswith("#") and not p.lower().startswith("chapters")]
    hook = text[0] if text else ""
    challenge = next((p for p in paras if p.lower().startswith("challenge:")), "")
    tags = []
    for t in re.findall(r"#\w+", description or ""):
        if t.lower() != "#shorts" and t.lower() not in (x.lower() for x in tags):
            tags.append(t)
    hook = re.sub(r"(\s*#\w+)+\s*$", "", hook).strip()
    out = "\n\n".join(x for x in (title, hook, challenge if challenge != hook else "", " ".join(tags[:30])) if x)
    return out[:2200]


TRIES = 5
NAMES = {"facebook": "Facebook", "instagram": "Instagram"}


def cross_post(ws, post, client=None, log=print, notify_fn=None):
    """Send a published YouTube Short to the Facebook Page and Instagram as Reels. Stores the result in post["meta"]
    ({"facebook": {"status", "url"|"error", "tries"}, "instagram": ...}); a platform already done is never posted twice."""
    yt = post.get("youtube") or {}
    if yt.get("format") != "short":
        return post
    conn = connection(ws)
    meta = post.setdefault("meta", {})
    if not conn:
        meta["skipped"] = "Facebook and Instagram are not connected (no secrets/meta.json in the factory)"
        return post
    meta.pop("skipped", None)
    from .agents.yt_publish import full_description
    cap = caption(yt.get("title"), full_description(post))
    m = client or Meta(conn["page_id"], conn["ig_user_id"], conn["token"], conn["version"])
    video = ws.root / post["media"]
    targets = ["facebook"] + (["instagram"] if conn["ig_user_id"] else [])
    for name in targets:
        cur = meta.get(name) or {}
        if cur.get("status") == "published" or cur.get("tries", 0) >= TRIES:
            continue
        try:
            fb_id = (meta.get("facebook") or {}).get("id")
            res = (m.facebook_reel(video, cap, log=log) if name == "facebook"
                   else m.instagram_reel(video, cap, facebook_id=fb_id, log=log))
            meta[name] = {"status": "published", "id": res["id"], "url": res["url"], "tries": cur.get("tries", 0) + 1}
            log(f"{name}: published {res['url']}")
        except (MetaError, OSError, KeyError) as e:
            meta[name] = {"status": "failed", "error": str(e)[:400], "tries": cur.get("tries", 0) + 1}
            log(f"{name}: failed: {e}")
            if notify_fn:
                left = TRIES - meta[name]["tries"]
                notify_fn(ws, f"{NAMES[name]} upload failed", f"{yt.get('title')} is on YouTube but not on {NAMES[name]}. "
                          + (f"Postcrew tries again later ({left} more times)." if left > 0 else "It gave up after 5 tries."),
                          level="error", key=f"meta-{name}-{post.get('id')}", action={"label": "Open Queue", "tab": "queue"},
                          details={"rows": [("Video", yt.get("title") or ""), (f"{NAMES[name]} said", str(e)[:300])]})
    return post


def retry_failed(ws, client=None, log=print, notify_fn=None):
    """Try the Facebook/Instagram posts that failed before again (Shorts already on YouTube). Returns how many were retried."""
    n = 0
    for h in ws.history():
        meta = h.get("meta") or {}
        if not any((meta.get(k) or {}).get("status") == "failed" and (meta.get(k) or {}).get("tries", 0) < TRIES for k in NAMES):
            continue
        if not h.get("media") or not (ws.root / h["media"]).exists():
            continue
        post = json.loads(json.dumps(h))
        cross_post(ws, post, client, log, notify_fn)
        ws.remove_history(lambda p: p.get("id") == h["id"] and (p.get("youtube") or {}).get("video_id") == (h.get("youtube") or {}).get("video_id"))
        ws.add_history(post)
        n += 1
    return n
