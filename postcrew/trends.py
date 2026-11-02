"""YouTube niche research: what is working right now on a subject, with numbers.

For a topic line (Settings > Topics) this searches YouTube the way a viewer does (this month, this year, Shorts and long videos), reads the
public watch page of the best candidates (views, likes, publish date, description, chapters, tags) and works out how trendy and how engaging the
subject is. The Planner turns the findings into plans; the Researcher later reads the same videos to learn how they are built.

  views per day   views / days since upload (a floor of 1 day): how fast a video is being watched
  engagement      likes / views, in percent
  trend score     0-100 from the median views per day of the recent videos (about 20 points per ten-fold step: 100 a day = 40, 10,000 a day = 80)
  label           hot (score 70+ with mostly recent videos), steady (45+), niche (anything below)

Nothing here needs an account or an API key. It reads public pages; when YouTube does not answer, the functions return empty results and the
caller carries on without numbers (the plan then says so). The network is injectable (`fetch`) so tests run offline.
"""
import json
import math
import re
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9", "Cookie": "CONSENT=YES+1; SOCS=CAI"}
PERIODS = {"month": "EgIIBA%3D%3D", "year": "EgIIBQ%3D%3D", "short": "EgIYAQ%3D%3D"}   # YouTube's own search filters: this month, this year, under 4 minutes
SUFFIXES = ("", " explained", " interview", " tutorial")
UNIT_DAYS = {"second": 0, "minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365,
             "s": 0, "min": 0, "h": 0, "d": 1, "w": 7, "mo": 30, "y": 365}


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------- parsing what YouTube shows ----------
def parse_views(text):
    """'3,255,515 views' -> 3255515; '1.2M views' -> 1200000; 'No views' -> 0; None when it is not a view count."""
    t = str(text or "").lower().replace(",", "")
    if "no views" in t:
        return 0
    m = re.search(r"([\d.]+)\s*([kmb]?)\s*views?", t)
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}[m.group(2)])


def parse_age(text):
    """'2y ago' / '6 months ago' / 'Streamed 3 weeks ago' / '5 hours ago' -> days (hours and minutes are 0); None when unknown."""
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year|mo|min|y|w|d|h|s)s?\b", str(text or "").lower())
    return int(m.group(1)) * UNIT_DAYS[m.group(2)] if m else None


def parse_duration(text):
    parts = [int(p) for p in re.findall(r"\d+", str(text or ""))]
    if not parts or len(parts) > 3:
        return None
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


def _initial(page, name):
    m = re.search(re.escape(name) + r"\s*=\s*(\{.*?\});\s*(?:var |</script>)", page, re.S)
    try:
        return json.loads(m.group(1)) if m else None
    except ValueError:
        return None


def _walk(obj, key, out):
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj[key])
        for v in obj.values():
            _walk(v, key, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, key, out)


def _text(node):
    if not isinstance(node, dict):
        return ""
    return node.get("simpleText") or "".join(r.get("text", "") for r in node.get("runs", []))


def parse_search(page):
    """The videos on a YouTube results page: [{id, title, channel, views, age_days, seconds}]."""
    data, found, out = _initial(page, "var ytInitialData") or {}, [], []
    _walk(data, "videoRenderer", found)
    for v in found:
        views = parse_views(_text(v.get("viewCountText")))
        if not v.get("videoId") or views is None:
            continue
        out.append({"id": v["videoId"], "title": _text(v.get("title")), "channel": _text(v.get("ownerText")), "views": views,
                    "age_days": parse_age(_text(v.get("publishedTimeText"))), "seconds": parse_duration(_text(v.get("lengthText")))})
    return out


def parse_chapters(description):
    """Timestamp lines of a description ('0:00 Intro', '2:15 Round robin') -> [{at, title}]."""
    out = []
    for line in str(description or "").splitlines():
        m = re.match(r"^\s*(?:[-•]\s*)?((?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—:]?\s*(.+?)\s*$", line)
        if m and parse_duration(m.group(1)) is not None:
            out.append({"at": parse_duration(m.group(1)), "title": m.group(2)[:90]})
    return out if len(out) >= 3 else []


def parse_watch(page):
    """What a watch page says: {views, likes, published, description, chapters, tags, title, channel}; missing parts are None/empty."""
    def grab(pattern, cast=str, number=True):
        m = re.search(pattern, page)
        if not m:
            return None
        try:
            return cast(m.group(1).replace(",", "") if number else m.group(1))
        except ValueError:
            return None
    desc = grab(r'"shortDescription":"((?:[^"\\]|\\.)*)"', str, False) or ""
    try:
        desc = json.loads('"' + desc + '"')
    except ValueError:
        pass
    tags = grab(r'"keywords":(\[[^\]]*\])', str, False) or "[]"
    try:
        tags = json.loads(tags)
    except ValueError:
        tags = []
    likes = grab(r'"likeCount":"?(\d+)', int)
    if likes is None:
        likes = grab(r"along with ([\d,]+) other people", int)
    return {"views": grab(r'"viewCount":"(\d+)"', int), "likes": likes, "published": grab(r'"publishDate":"([^"]+)"', str, False),
            "description": desc[:2500], "chapters": parse_chapters(desc), "tags": tags[:15]}


# ---------- finding and measuring ----------
def search(query, period="", fetcher=None):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query) + (f"&sp={PERIODS[period]}" if period in PERIODS else "")
    try:
        return parse_search((fetcher or fetch)(url))
    except Exception:   # noqa: BLE001 (research is best effort: no answer means no numbers)
        return []


def video_info(video_id, fetcher=None):
    try:
        return parse_watch((fetcher or fetch)(f"https://www.youtube.com/watch?v={video_id}"))
    except Exception:   # noqa: BLE001
        return {}


def age_from_published(published, now=None):
    try:
        d = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        return max(0, ((now or datetime.now(timezone.utc)) - (d if d.tzinfo else d.replace(tzinfo=timezone.utc))).days)
    except ValueError:
        return None


def with_rates(v):
    """A video with its views per day and engagement filled in."""
    age = v.get("age_days")
    v = dict(v, url=f"https://www.youtube.com/watch?v={v['id']}")
    v["views_per_day"] = round(v["views"] / max(1, age if age is not None else 365), 1)
    v["engagement_pct"] = round(100 * v["likes"] / v["views"], 2) if v.get("likes") is not None and v.get("views") else None
    v["short"] = bool(v.get("seconds") and v["seconds"] <= 180)
    return v


def metrics(videos):
    """How trendy and how engaging a set of videos is: the numbers a plan shows. {} for no videos."""
    vids = [v for v in videos if v.get("views") is not None]
    if not vids:
        return {}
    recent = [v for v in vids if (v.get("age_days") if v.get("age_days") is not None else 9999) <= 365]
    basis = recent or vids
    per_day = statistics.median(v["views_per_day"] for v in basis)
    score = max(0, min(100, round(20 * math.log10(1 + per_day))))
    fresh = sum(1 for v in vids if (v.get("age_days") if v.get("age_days") is not None else 9999) <= 90) / len(vids)
    liked = [v for v in vids if v.get("engagement_pct") is not None]
    label = "hot" if score >= 70 and fresh >= 0.3 else "steady" if score >= 45 else "niche"
    return {"videos": len(vids), "avg_views": round(statistics.mean(v["views"] for v in vids)), "median_views": round(statistics.median(v["views"] for v in vids)),
            "avg_likes": round(statistics.mean(v["likes"] for v in liked)) if liked else None,
            "engagement_pct": round(statistics.mean(v["engagement_pct"] for v in liked), 2) if liked else None,
            "views_per_day": round(per_day, 1), "recent_share": round(fresh, 2), "trend_score": score, "label": label}


def niche_research(topic, fetcher=None, max_videos=14, log=None):
    """Search the topic on YouTube (a few phrasings, this month / this year / Shorts), read the best candidates and measure them.
    {"topic", "videos": [...with views, likes, age, rates, description, chapters, tags...], "metrics", "researched_at", "error"?}"""
    seen, hits = {}, []
    for suffix in SUFFIXES:
        for period in ("month", "year", "short") if suffix == "" else ("year",):
            for v in search(topic + suffix, period, fetcher):
                if v["id"] not in seen:
                    seen[v["id"]] = v
                    hits.append(v)
    out = {"topic": topic, "researched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "videos": [], "metrics": {}}
    if not hits:
        out["error"] = "YouTube did not answer: the plan was written without view and like numbers"
        return out
    ranked = sorted((with_rates(dict(v, age_days=v["age_days"])) for v in hits), key=lambda v: -v["views_per_day"])
    for v in ranked[:max_videos]:   # the likes, the publish date and the description are on the watch page
        info = video_info(v["id"], fetcher)
        v.update({k: info.get(k) for k in ("likes", "description", "chapters", "tags")})
        if info.get("views"):
            v["views"] = info["views"]
        if info.get("published") and age_from_published(info["published"]) is not None:
            v["age_days"] = age_from_published(info["published"])
        out["videos"].append(with_rates(v))
        if log:
            log(f"{v['title'][:60]}: {v['views']:,} views")
    out["videos"].sort(key=lambda v: -v["views_per_day"])
    out["metrics"] = metrics(out["videos"])
    return out


def brief_videos(videos, limit=12):
    """The compact list a model reads: id, title, channel, views, likes, engagement, age, length, views per day."""
    rows = []
    for v in videos[:limit]:
        rows.append(f"{v['id']} | {v['title'][:80]} | {v.get('channel', '')[:24]} | {v['views']:,} views | "
                    + (f"{v['likes']:,} likes ({v['engagement_pct']}%)" if v.get("likes") is not None else "likes n/a")
                    + f" | {v.get('age_days', '?')} days old | {'Short' if v.get('short') else 'long'} | {v['views_per_day']:,} views/day")
    return "\n".join(rows)


def evidence(videos, ids):
    """The chosen videos in full, for a plan's details: [{id, title, channel, views, likes, engagement_pct, age_days, url, short}]."""
    by = {v["id"]: v for v in videos}
    keep = ("id", "title", "channel", "views", "likes", "engagement_pct", "age_days", "views_per_day", "url", "short", "chapters")
    return [{k: by[i].get(k) for k in keep} for i in ids if i in by]
