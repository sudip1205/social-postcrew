"""YouTube analytics for the channel Postcrew is connected to: every video on it, with what the crew made marked.

Two sources:
  * the YouTube Data API (what the connection always had, youtube.readonly): the channel's subscribers and total views, and each video's
    views, likes and comments;
  * the YouTube Analytics API (yt-analytics.readonly, asked for by connections made from now on): watch time, average view duration, how
    much of the video people watch, shares and subscribers gained per video, and the channel's daily views over the last 28 days.
    Without it (an older connection, or the API not turned on in Google Cloud) the page shows the counts and says what to do.

Cached in state/yt-analytics.json for 30 minutes (a refresh costs a handful of the 10,000 daily quota units).
"""
from datetime import date, datetime, timedelta, timezone

from .youtube import YouTube, YouTubeError

CACHE = "yt-analytics"
FRESH = timedelta(minutes=30)
PER_VIDEO = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained"
DAILY = "views,estimatedMinutesWatched,subscribersGained,subscribersLost"


def client(ws, client_factory=YouTube):
    s = ws.secrets()
    if not (s.get("youtube_client_id") and s.get("youtube_client_secret") and s.get("youtube_refresh_token")):
        return None
    return client_factory(s["youtube_client_id"], s["youtube_client_secret"], s["youtube_refresh_token"])


def crew_made(ws):
    """{video id: what Postcrew knows of it} for the videos the crew uploaded."""
    from . import rewards
    pts = rewards.load(ws)["posts"]
    out = {}
    for h in ws.history():
        yt = h.get("youtube") or {}
        if h.get("platform") == "youtube" and yt.get("video_id"):
            out[yt["video_id"]] = {"post_id": h.get("id"), "run_id": h.get("run_id"), "topic": h.get("topic"), "format": yt.get("format"),
                                   "category": h.get("category"), "points": (pts.get(h.get("id")) or {}).get("delta"),
                                   "picture_score": (yt.get("picture") or {}).get("score")}
    return out


def build(ws, client_factory=YouTube, today=None, days=28):
    yt = client(ws, client_factory)
    if not yt:
        return {"connected": False, "message": "YouTube is not connected: connect it in Credentials."}
    today = today or date.today()
    ch = yt.channel_stats()
    vids = yt.videos(yt.uploads(ch["uploads"])) if ch["uploads"] else []
    vids = [v for v in vids if v.get("privacy") == "public"]   # private and unlisted videos are left out
    mine = crew_made(ws)
    for v in vids:
        v["crew"] = mine.get(v["id"])
        v["format"] = (v["crew"] or {}).get("format") or ("short" if (v.get("seconds") or 0) <= 180 else "long")
    analytics = {"ok": True}
    if vids:
        start = min((v["published_at"] or today.isoformat())[:10] for v in vids)
        try:
            rows = yt.report(start, today.isoformat(), PER_VIDEO, dimensions="video", sort="-views", limit=200)
            by = {r["video"]: r for r in rows}
            for v in vids:
                r = by.get(v["id"]) or {}
                v["analytics"] = {k: r.get(k) for k in PER_VIDEO.split(",")} if r else None
            daily = yt.report((today - timedelta(days=days)).isoformat(), today.isoformat(), DAILY, dimensions="day", sort="day")
            analytics["daily"] = daily
        except YouTubeError as e:
            not_on = "has not been used" in str(e) or "disabled" in str(e) or "accessNotConfigured" in str(e)
            analytics = {"ok": False, "error": str(e)[:300],
                         "message": ("Turn on the \"YouTube Analytics API\" in Google Cloud (APIs & Services > Library) for the project of your "
                                     "YouTube app, then refresh." if not_on else
                                     "Watch time, retention and subscribers per video need one more permission: reconnect YouTube in "
                                     "Credentials (pick the Dip-to-Dive channel again) and allow \"View YouTube Analytics reports\". "
                                     "If it still fails, turn on the \"YouTube Analytics API\" in Google Cloud for your YouTube app's project.")
                         if e.kind in ("auth", "invalid") else str(e)[:300]}
    crew = [v for v in vids if v["crew"]]
    total = lambda rows, k: sum((r.get(k) or 0) for r in rows)
    return {"connected": True, "channel": {k: ch[k] for k in ("id", "title", "subscribers", "views", "videos")},
            "videos": vids, "analytics": analytics, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": {"videos": len(vids), "crew_videos": len(crew), "crew_views": total(crew, "views"), "crew_likes": total(crew, "likes"),
                        "crew_comments": total(crew, "comments"),
                        "crew_minutes": round(sum(((v.get("analytics") or {}).get("estimatedMinutesWatched") or 0) for v in crew)),
                        "best": max(crew, key=lambda v: v.get("views") or 0)["title"] if crew else None}}


def overview(ws, client_factory=YouTube, refresh=False, today=None):
    """What the Analytics page shows; from the cache when it is fresh."""
    c = ws.state(CACHE, {}) or {}
    if not refresh and c.get("fetched_at") and datetime.now(timezone.utc) - datetime.fromisoformat(c["fetched_at"]) < FRESH:
        return dict(c, cached=True)
    try:
        d = build(ws, client_factory, today=today)
    except YouTubeError as e:
        if c.get("fetched_at"):
            return dict(c, cached=True, error=str(e)[:300])
        return {"connected": True, "error": str(e)[:300], "videos": []}
    if d.get("connected"):
        ws.save_state(CACHE, d)
    return d
