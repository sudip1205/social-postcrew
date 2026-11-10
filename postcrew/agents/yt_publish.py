"""YouTube publishing: queue a finished video, and upload it at its time. Same rules as LinkedIn's publisher.py:
the approval mode decides whether it waits for you (manual), goes out at its time unless you veto it (auto_with_veto) or
right away (immediate); with publishing.dry_run on, nothing is sent. Uploading uses the official YouTube Data API."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .. import platforms, seo
from ..notify import notify
from ..runlog import RunLog
from ..youtube import YouTube, YouTubeError
from .credentials import GOOD, check_youtube
from .planner import plan_id_for
from .publisher import post_details, scheduled_at

LABEL = "YouTube"


def enqueue_youtube(ws, cfg, run_id, day, category, outputs, review):
    """Queue the finished video. cfg: the app's view of the config. outputs: the run's accepted outputs."""
    if "slug" in (outputs.get("writer") or {}):   # made by the Shorts factory (agents/shorts.py)
        return _enqueue_short(ws, cfg, run_id, day, category, outputs)
    script, video, voice = outputs["writer"], outputs["media"], outputs.get("voice") or {}
    try:   # the scenes as they were drawn (after the Storyboard Artist and any redraw): the model a video you approve leaves (rewards.py)
        (ws.runs_dir / run_id / "script.final.json").write_text(json.dumps(script, indent=1, default=str))
    except OSError:
        pass
    platform = cfg.get("platform", "youtube")
    pid = f"{day.isoformat()}-{platform}-{category}"
    plan_id = plan_id_for(ws, platform, day, category)   # a day can hold several plans, made one at a time: each post is its own
    if plan_id:
        pid += f"-{plan_id}"
    media_dir = ws.root / "media"
    media_dir.mkdir(exist_ok=True)
    dest = media_dir / f"{pid}.mp4"
    shutil.copy2(video["path"], dest)
    thumb = media_dir / f"{pid}.png"
    shutil.copy2(video["thumbnail_path"], thumb)
    mode = cfg["publishing"]["approval"]
    if (outputs.get("hooks") or {}).get("unresolved"):   # a fault the Hooks agent could not fix: a person decides, whatever the approval setting
        mode = "manual"
    if (outputs.get("quality") or {}).get("held"):   # the Quality Director still finds the picture weak after its redraws: a person decides
        mode = "manual"
    post = {
        "id": pid, "platform": platform, "run_id": run_id, "date": day.isoformat(), "category": category,
        "topic": script["title"], "text": script["description"], "first_comment": "",
        "media": str(dest.relative_to(ws.root)), "media_kind": "video", "poster_image": str(thumb.relative_to(ws.root)),
        "status": "awaiting_approval" if mode == "manual" else "queued",
        "scheduled_at": scheduled_at(cfg, day) if mode != "immediate" else datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "review": {k: review.get(k) for k in ("overall", "scores")},
        **({"plan_id": plan_id} if plan_id else {}),
        "youtube": {
            "title": script["title"], "description": script["description"], "tags": script["tags"],
            "format": video.get("format") or ("short" if video["height"] > video["width"] else "long"),
            "seconds": video["seconds"], "thumbnail_text": script.get("thumbnail_text", ""),
            "voice": voice.get("voice") or ("own" if video.get("voice") == "own" else "none"),
            "scenes": _scenes(script["scenes"], video),
            "source": {"script": script.get("source", "crew"),
                       "voice": "own" if video.get("voice") == "own" else ("crew" if voice.get("mode") in ("elevenlabs", "local") else "none"),
                       "video": video.get("source", "crew")},
            "video_id": None, "url": None,
        },
    }
    gate = outputs.get("hooks")   # the Hooks agent's check of sound and frames (no AI)
    if gate:
        post["youtube"]["quality"] = {k: gate.get(k) for k in ("score", "repaired", "checked")}
    q = outputs.get("quality")   # the Quality Director's verdict on the finished picture
    if q:
        post["youtube"]["picture"] = {k: q.get(k) for k in ("score", "scores", "summary", "held", "redrawn", "round", "vision")}
        post["youtube"]["picture"]["notes"] = ([f["message"] for f in q.get("findings") or []] + list(q.get("problems") or []))[:10]
    check = outputs.get("video_review")   # the Video Editor's verdict on the finished video (blackboard videos)
    if check:
        post["youtube"]["video_review"] = {k: check.get(k) for k in ("verdict", "score", "first_score", "redrawn", "summary", "measured")}
    ws.save_queue([p for p in ws.queue() if p["id"] != pid] + [post])
    return post


def _enqueue_short(ws, cfg, run_id, day, category, outputs):
    """Queue a Short the factory made: its video, thumbnail and youtube.json (title, description, tags)."""
    w, video = outputs["writer"], outputs["media"]
    platform = cfg.get("platform", "youtube")
    pid = f"{day.isoformat()}-{platform}-{category}"
    plan_id = plan_id_for(ws, platform, day, category)
    if plan_id:
        pid += f"-{plan_id}"
    media_dir = ws.root / "media"
    media_dir.mkdir(exist_ok=True)
    dest = media_dir / f"{pid}.mp4"
    shutil.copy2(video["path"], dest)
    thumb = None
    if video.get("thumbnail_path") and Path(video["thumbnail_path"]).exists():
        thumb = media_dir / f"{pid}{Path(video['thumbnail_path']).suffix}"
        shutil.copy2(video["thumbnail_path"], thumb)
    mode = cfg["publishing"]["approval"]
    post = {
        "id": pid, "platform": platform, "run_id": run_id, "date": day.isoformat(), "category": category,
        "topic": w["title"], "text": w["description"], "first_comment": "",
        "media": str(dest.relative_to(ws.root)), "media_kind": "video", **({"poster_image": str(thumb.relative_to(ws.root))} if thumb else {}),
        "status": "awaiting_approval" if mode == "manual" else "queued",
        "scheduled_at": scheduled_at(cfg, day) if mode != "immediate" else datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "review": {},
        **({"plan_id": plan_id} if plan_id else {}),
        "youtube": {"title": w["title"], "description": w["description"], "tags": w["tags"], "format": "short",
                    "seconds": video["seconds"], "thumbnail_text": "", "voice": "kokoro", "scenes": [],
                    "episode": w["slug"], "source": {"script": "shorts-factory", "voice": "kokoro", "video": video.get("engine", "shorts-factory")},
                    "video_id": None, "url": None},
    }
    ws.save_queue([p for p in ws.queue() if p["id"] != pid] + [post])
    return post


def _scenes(scenes, video):
    """The scenes as kept with the post. When the video says how long each scene really is, that is used (the script only estimated)."""
    real = video.get("scene_seconds") or []
    out = [{"narration": s["narration"], "on_screen": s.get("on_screen", ""),
            "seconds": real[i] if i < len(real) else s.get("seconds", 0)} for i, s in enumerate(scenes)]
    if video.get("closing") and out:
        out[-1]["closing"] = True
    return out


def full_description(post):
    """The description as uploaded: what the Script Writer wrote, then (for a long video) real chapters from the scene lengths, then three
    hashtags (the first three are shown above the title), and #Shorts for a Short so YouTube files it under Shorts."""
    yt = post["youtube"]
    desc = yt["description"].rstrip()
    chaps = seo.chapters(yt.get("scenes") or [], yt["format"])
    if chaps and "0:00" not in desc:
        desc += "\n\nChapters\n" + chaps
    desc = seo.with_hashtags(desc, yt.get("tags"), 2 if yt["format"] == "short" else 3)
    if yt["format"] == "short" and "#shorts" not in desc.lower():
        desc += " #Shorts" if desc.rstrip().splitlines()[-1].startswith("#") else "\n\n#Shorts"
    return desc


def publish_one(ws, post, client_factory=YouTube, log=print, check=check_youtube, meta_client=None):
    """Upload one queued video. Returns the updated post (status published | dry_run | failed | queued when blocked)."""
    cfg = platforms.view(ws.config(), "youtube")
    run = RunLog(ws.runs_dir / post["run_id"]) if post.get("run_id") and (ws.runs_dir / post["run_id"]).exists() else None

    def ev(kind, msg, level="info"):
        log(msg)
        if run:
            run.event("publisher", kind, msg, level=level)

    yt = post["youtube"]
    if cfg["publishing"]["dry_run"]:
        ev("dry_run", f"DRY RUN - would upload '{yt['title']}' ({yt['format']}, {yt['seconds']:.0f}s) to YouTube as "
                      f"{cfg['publishing'].get('visibility', 'public')}. Turn off practice mode in Settings to upload for real.")
        post.update(status="dry_run", published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if run:
            run.step("publisher", "passed", summary="dry run: nothing uploaded")
        return post
    state = check(ws, ws.config(), True, client_factory)
    if state["state"] not in GOOD:
        post.update(status="queued", error=state["message"])
        ev("blocked", f"not uploaded: {state['message']}", "error")
        if run:
            run.step("publisher", "blocked", summary="YouTube credentials invalid")
        notify(ws, "YouTube connection needs attention", state["message"], level="error", key="youtube-" + state["state"],
               action={"label": "Open Credentials", "tab": "credentials"})
        return post
    s = ws.secrets()
    client = client_factory(s["youtube_client_id"], s["youtube_client_secret"], s["youtube_refresh_token"])
    pub = cfg["publishing"]
    # The channel guard: a reconnect that picked another channel (a personal one instead of the brand channel, say) must not send videos
    # there without you knowing. The channel of the last upload is remembered; a different one stops the upload until you approve again.
    try:
        channel = client.channel()
    except YouTubeError:
        channel = None
    last = ws.state("youtube_channel", {}) or {}
    if channel and last.get("id") and channel["id"] != last["id"] and post.get("channel_ok") != channel["id"]:
        msg = (f"YouTube is now connected to the channel \"{channel['title']}\", but your videos went to \"{last.get('title')}\" until now. "
               f"Not uploaded. To use \"{last.get('title')}\", reconnect YouTube in Credentials and pick that channel; to upload to "
               f"\"{channel['title']}\" from now on, approve this video again in the Queue.")
        post.update(status="awaiting_approval", error=msg, channel_switch={"from": last, "to": channel})
        ev("channel_changed", msg, "error")
        if run:
            run.step("publisher", "blocked", summary="YouTube channel changed: waiting for you")
        notify(ws, "YouTube channel changed: video not uploaded", msg, level="error", key=f"channel-{post['id']}",
               action={"label": "Open Credentials", "tab": "credentials"})
        return post
    try:
        ev("upload", f"uploading {Path(post['media']).name}" + (f" to the channel \"{channel['title']}\"" if channel else ""))
        res = client.upload(ws.root / post["media"], yt["title"], full_description(post), seo.normalize_tags(yt["tags"], yt["title"]),
                            category_id=pub.get("category_id", "28"), privacy=pub.get("visibility", "public"),
                            made_for_kids=bool(pub.get("made_for_kids", False)),
                            progress=lambda sent, total: ev("upload", f"{sent * 100 // max(total, 1)}% uploaded"))
    except YouTubeError as e:
        # a quota or upload-limit stop lifts by itself (YouTube resets the quota daily): keep it queued, try again later
        post.update(status="queued" if e.kind in ("quota", "auth") else "failed", error=str(e))
        ev("failed", f"upload failed: {e}", "error")
        if run:
            run.step("publisher", "failed", errors=[str(e)])
        notify(ws, "YouTube upload failed", f"{yt['title']} was not uploaded. It stays in the queue.", level="error",
               key=f"publish-{post['id']}", action={"label": "Open Queue", "tab": "queue"},
               details={"rows": [("Video", yt["title"]), ("YouTube said", str(e)[:300]),
                                 ("What to do", "Reconnect YouTube in Credentials." if e.kind == "auth" else
                                  "YouTube's daily upload quota is used up: it tries again tomorrow." if e.kind == "quota"
                                  else "Check the message, then publish it again from the Queue.")]})
        return post
    thumb_note = ""
    try:
        if post.get("poster_image"):
            client.set_thumbnail(res["id"], ws.root / post["poster_image"])
    except YouTubeError as e:   # custom thumbnails need a verified channel: the video is up anyway
        thumb_note = f" (thumbnail not set: {e})"
        ev("thumbnail", f"the video is up, but its thumbnail was not set: {e}", "warning")
    yt.update(video_id=res["id"], url=res["url"], **({"channel": channel["title"], "channel_id": channel["id"]} if channel else {}))
    post.update(status="published", published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), error=None)
    post.pop("channel_switch", None)
    if channel:
        ws.save_state("youtube_channel", channel)
    ev("published", f"uploaded {res['url']}" + (f" to the channel \"{channel['title']}\"" if channel else "") + thumb_note)
    if run:
        run.step("publisher", "passed", summary=f"uploaded {res['url']}")
    if yt["format"] == "short":   # every Short that goes to YouTube also goes to Facebook and Instagram as a Reel
        from .. import meta
        try:
            meta.cross_post(ws, post, client=meta_client, log=lambda m: ev("meta", m), notify_fn=notify)
        except Exception as e:   # never lose the YouTube upload over the other apps
            post.setdefault("meta", {})["error"] = f"{type(e).__name__}: {e}"[:400]
            ev("meta", f"Facebook/Instagram skipped: {e}", "error")
    ws.add_history({k: post.get(k) for k in ("id", "platform", "date", "category", "topic", "text", "media", "published_at",
                                             "run_id", "youtube", "plan_id", "meta")})
    social = [(f"Reel on {n}", (post.get("meta") or {}).get(k, {}).get("url") or (post.get("meta") or {}).get(k, {}).get("error", ""))
              for k, n in (("facebook", "Facebook"), ("instagram", "Instagram")) if (post.get("meta") or {}).get(k)]
    notify(ws, "Uploaded to YouTube", f"{yt['title']} is on your channel" + (f" \"{channel['title']}\"." if channel else "."), level="success",
           action={"label": "Open Queue", "tab": "queue"},
           details=post_details(ws, post, ("Video on YouTube", res["url"]), *social))
    return post
