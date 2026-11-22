"""YouTube tags (owner, 2026-11-21: "tags are not good, that is why the video is not reaching people. Tag it properly based on the topic.
List out tags during topic plan").

The Planner writes tags with every YouTube plan, starting from the tags the top videos for the topic really use (trends.niche_research
reads them from each watch page); the Factory shows them on the plan; the Script Writer's youtube.json starts from them, and the upload
sends them.
"""
import re
from collections import Counter

MAX_CHARS = 480   # YouTube allows 500 characters of tags (a tag with a space counts its quotes too); keep a margin
MIN_TAGS = 10

TAG_RULE = (
    "YOUTUBE TAGS (owner rule, 2026-11-21: tags decide who the video reaches). Write 15-25 tags, most important first, all about THIS video's "
    "topic: 1) the exact topic as people search it ('egg drop problem', 'how wifi works'); 2) its other names, abbreviations and spellings "
    "('2 eggs 100 floors', 'egg dropping puzzle'); 3) long-tail questions and phrases viewers type ('egg drop puzzle explained', 'minimum "
    "drops 2 eggs'); 4) the wider field ('dynamic programming', 'algorithms', 'computer science'); 5) the audience's goal ('coding interview "
    "question', 'learn algorithms') and the format ('animated explanation', 'shorts'). Use the tags the top videos use where they fit. "
    "Lower case, no '#', no channel name, no tags about other topics, no single generic words alone ('video', 'tech', 'learn'), each at most "
    "30 characters, all together under 480 characters.")

TAGS_SCHEMA = {"type": "array", "items": {"type": "string"}, "minItems": MIN_TAGS, "maxItems": 30,
               "description": "15-25 YouTube tags for this video, most important first (see YOUTUBE TAGS)"}

GENERIC = {"video", "videos", "youtube", "shorts", "short", "tech", "technology", "learn", "learning", "education", "tutorial", "new",
           "viral", "trending", "fyp", "subscribe"}


def _size(tags):
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)


def clean(tags, limit=MAX_CHARS):
    """Tidy tags: no '#', quotes or doubled spaces, lower case, at most 30 characters, no repeats, within YouTube's character budget."""
    out, seen = [], set()
    for t in tags or []:
        t = re.sub(r"\s+", " ", re.sub(r"[#\"<>,]", " ", str(t or ""))).strip().lower()
        if not t or len(t) > 30 or t in seen:
            continue
        if _size(out + [t]) > limit:
            continue
        seen.add(t)
        out.append(t)
    return out


def merge(*lists, limit=MAX_CHARS):
    """The first list wins its order; later lists only add what is missing."""
    return clean([t for lst in lists for t in (lst or [])], limit)


def problems(tags):
    """Why a plan's or a video's tags are not good enough yet ([] when they are)."""
    got = clean(tags)
    out = []
    if len(got) < MIN_TAGS:
        out.append(f"only {len(got)} usable YouTube tags: write 15-25 about this topic (YOUTUBE TAGS)")
    alone = [t for t in got if t in GENERIC]
    if len(alone) > 2:
        out.append(f"too many generic tags ({', '.join(alone)}): use what people search for this topic instead")
    return out


def competitors(videos, top=25):
    """The tags the researched top videos use, most common first (each counted once per video)."""
    c = Counter()
    for v in videos or []:
        for t in clean(v.get("tags") or [], limit=10_000):
            c[t] += 1
    return [t for t, _ in c.most_common(top)]
