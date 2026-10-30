"""What helps a video be found: clean tags, three hashtags, and real chapters. No AI: it only tidies what the Script Writer wrote and
adds what is known for certain (the real length of every scene).

YouTube rules this follows: a tag is at most 30 characters and all tags together at most 500; the first three hashtags of a description
are shown above the title; chapters are lines "0:00 Title" (the first at 0:00, at least three, each at least ten seconds) and are only
used for a long video.
"""
import re

TAGS_MAX_CHARS = 460   # YouTube counts a little more than the letters (quotes round tags with spaces): stay under its 500
TAGS_MAX = 15
MIN_CHAPTER_S = 10


def normalize_tags(tags, title=""):
    """Tags as uploaded: no #, no repeats (any capitals), none over 30 characters, at most 15 and 460 characters in all. The order is kept:
    the first tags matter most."""
    out, seen, total = [], set(), 0
    for t in tags or []:
        t = re.sub(r"\s+", " ", str(t).replace("#", "").replace(",", " ")).strip()
        if not t or len(t) > 30 or t.lower() in seen:
            continue
        cost = len(t) + 1 + (2 if " " in t else 0)
        if len(out) >= TAGS_MAX or total + cost > TAGS_MAX_CHARS:
            break
        seen.add(t.lower())
        out.append(t)
        total += cost
    return out


def hashtag(tag):
    """'circuit breaker pattern' -> '#CircuitBreakerPattern' (letters and digits only)."""
    words = re.findall(r"[A-Za-z0-9]+", tag)
    return "#" + "".join(w[:1].upper() + w[1:] for w in words) if words else ""


def with_hashtags(description, tags, count=3):
    """The description with three hashtags at the end (taken from the first tags), unless it already has that many."""
    have = re.findall(r"#\w+", description)
    if len(have) >= count:
        return description
    tagged = {h.lower() for h in have}
    extra = []
    for t in tags or []:
        h = hashtag(t)
        if h and h.lower() not in tagged and len(h) <= 30 and len(have) + len(extra) < count:
            extra.append(h)
            tagged.add(h.lower())
    return description.rstrip() + ("\n\n" + " ".join(extra) if extra else "")


def stamp(seconds):
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def chapters(scenes, fmt="long"):
    """The chapter lines of a long video from its scenes ({"on_screen", "seconds", "closing"?}), or "" when there cannot be a valid set.
    The first scene is the introduction; a scene shorter than ten seconds joins the chapter before it; the closing card is not a chapter."""
    if fmt != "long" or not scenes:
        return ""
    starts, t = [], 0.0
    for i, sc in enumerate(scenes):
        sec = float(sc.get("seconds") or 0)
        if not sc.get("closing"):
            name = "Introduction" if i == 0 else (re.sub(r"\s+", " ", sc.get("on_screen") or "").strip(" .·") or f"Part {i + 1}")
            starts.append((t, sec, name[:60]))
        t += sec
    chaps = []
    for start, sec, name in starts:
        if chaps and (start - chaps[-1][0] < MIN_CHAPTER_S or sec < MIN_CHAPTER_S):
            if sec < MIN_CHAPTER_S and chaps[-1][0] + MIN_CHAPTER_S <= start:
                continue   # too short on its own: it stays inside the chapter before
            if start - chaps[-1][0] < MIN_CHAPTER_S:
                chaps[-1] = (chaps[-1][0], chaps[-1][1] + sec, chaps[-1][2])
                continue
        chaps.append((start, sec, name))
    if len(chaps) < 3 or chaps[0][0] != 0:
        return ""
    return "\n".join(f"{stamp(s)} {n}" for s, _sec, n in chaps)
