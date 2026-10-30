"""Deterministic checks: the ones an LLM cannot fake. Each returns a list of problems (empty = pass).

Sources are re-fetched and every quote must really be on the page; money/percent/big numbers in the post
must appear in those sources; code must parse; links must be verified sources; nothing may repeat a
recent post.
"""
import ast
import difflib
import json
import re
import subprocess
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

SLOP = ["game-changer", "game changer", "delve", "in today's fast-paced", "unlock the power", "revolutionize",
        "buckle up", "let that sink in", "here's the kicker", "mind-blowing", "10x your"]
PLACEHOLDER = re.compile(r"\[YOUR|\[INSERT|\bTODO\b|\bTBD\b|lorem ipsum|\bXXX\b|\{\{|\}\}|\[\[|\]\]|"
                         r"<(?:your|insert|name|link|url|todo)[^>]*>", re.I)
INVENTED = re.compile(r"\b(I|we) (built|shipped|tested|benchmarked|measured|saw|migrated|deployed|launched)\b|"
                      r"\blast (week|month|year) (I|we)\b|\bat (my|our) (company|job|work|team)\b", re.I)
URL = re.compile(r"https?://[^\s)>\]]+")
LINKEDIN_LIMIT = 3000


def norm(s):
    s = (s or "").lower()
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"),
                 ("—", "-"), (" ", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def norm_url(u):
    return u.strip().rstrip("/.,;").lower()


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def fetch_text(url, timeout=20, max_bytes=1_500_000):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; postcrew/1.0)",
                                               "Accept": "text/html,application/xhtml+xml,text/plain"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(max_bytes)
        charset = r.headers.get_content_charset() or "utf-8"
    p = _Text()
    p.feed(raw.decode(charset, errors="replace"))
    return " ".join(p.parts)


def significant_numbers(s):
    s = URL.sub(" ", s)
    s = re.sub(r"(?m)^\s*\d+[.)]\s", " ", s)  # list markers
    out = []
    for m in re.finditer(r"\$?\d[\d,]*(?:\.\d+)?%?", s):
        tok = m.group()
        if any(c in tok for c in "%$.,") or len(re.sub(r"\D", "", tok)) >= 2:
            out.append(tok)
    return out


def bare(tok):
    return tok.replace(",", "").replace("$", "").replace("%", "").rstrip(".")


def emoji_count(s):
    return sum(1 for ch in s if ord(ch) >= 0x1F300 or 0x2600 <= ord(ch) <= 0x27BF)


# ---------- sources ----------
def verify_sources(sources, fetch=fetch_text, limit=6):
    """Re-fetch each source; a source is verified when at least one of its quotes is on the page."""
    out = []
    for s in (sources or [])[:limit]:
        url = (s.get("url") or "").strip()
        info = {"url": url, "title": s.get("title", ""), "published": s.get("published", ""),
                "excerpts": [e for e in s.get("excerpts", []) if e], "verified": False, "found": [], "page": ""}
        if not url.startswith("https://"):
            info["error"] = "source url must start with https://"
        else:
            try:
                info["page"] = norm(fetch(url))
                info["found"] = [e for e in info["excerpts"] if len(norm(e)) >= 20 and norm(e) in info["page"]]
                info["verified"] = bool(info["found"])
                if not info["verified"]:
                    info["error"] = "none of the quoted excerpts were found on the page (quotes must be verbatim)"
            except Exception as e:  # network error, paywall, 404 ...
                info["error"] = f"could not fetch: {str(e)[:120]}"
        out.append(info)
    return out


STALE = "the topic is too old for this category: the newest verified source is from"


def source_problems(verified, research_mode, max_age_days=None, today=None):
    problems = []
    good = [s for s in verified if s["verified"]]
    if research_mode == "required" and not good:
        detail = "; ".join(f"{s['url']}: {s.get('error', '')}" for s in verified) or "no sources given"
        problems.append(f"need at least one verified https source with a verbatim quote ({detail})")
    if research_mode == "required" and max_age_days and good:
        today = today or date.today()
        start = today - timedelta(days=max_age_days)
        dates = []
        for s in good:
            try:
                dates.append(datetime.strptime(s["published"][:10], "%Y-%m-%d").date())
            except ValueError:
                pass
        if not any(start <= d <= today for d in dates):
            if dates and max(dates) < start:  # the sources are dated and all too old: the story itself is stale
                problems.append(f"{STALE} {max(dates).isoformat()}, but sources must be published between "
                                f"{start.isoformat()} and {today.isoformat()}; choose a newer topic")
            else:
                problems.append(f"need a verified source published between {start.isoformat()} and "
                                f"{today.isoformat()} (set 'published' to the YYYY-MM-DD date shown on the page)")
    return problems


# ---------- text ----------
def text_problems(text, cat, profile, first_comment=""):
    problems = []
    n = len(text)
    lo, hi = cat.get("min_chars", 50), cat.get("max_chars", 3000)
    if not lo <= n <= hi:
        problems.append(f"length is {n} characters; LinkedIn posts must be {lo}-{hi}")
    hook = next((ln for ln in text.split("\n") if ln.strip()), "")
    if not 15 <= len(hook) <= 180:
        problems.append(f"first line (the hook) is {len(hook)} characters; keep it 15-180")
    everything = text + "\n" + (first_comment or "")
    m = PLACEHOLDER.search(everything)
    if m:
        problems.append(f"remove the placeholder {m.group()!r}")
    bad = [b for b in profile.get("blocklist", []) if re.search(r"\b" + re.escape(b) + r"\b", everything, re.I)]
    if bad:
        problems.append(f"contains blocked phrase(s): {bad}")
    slop = [s for s in SLOP if s in text.lower()]
    if slop:
        problems.append(f"remove hype phrases: {slop}")
    if "**" in text or re.search(r"(?m)^#{1,6} ", text) or "`" in text:
        problems.append("LinkedIn does not render markdown: no **, no # headings, no backticks")
    if len(re.findall(r"(?<!\w)#\w+", text)) > 5:
        problems.append("use at most 5 hashtags")
    if emoji_count(text) > 3:
        problems.append("use at most 3 emoji")
    about = norm(" ".join(profile.get("about", [])))
    for m in INVENTED.finditer(text):
        if norm(m.group()) not in about:
            problems.append(f"'{m.group()}' claims personal experience that is not in profile.about; "
                            f"rephrase as advice or opinion")
            break
    return problems


YOUTUBE_TITLE_MAX, YOUTUBE_DESC_MAX, YOUTUBE_TAGS_MAX = 100, 5000, 500
from . import speech  # noqa: E402

SCENE_LAYOUTS = ("title", "statement", "points", "code", "diagram", "trace", "flow")


SENTENCE_MAX = 30


def needed_visual(spec, cat):
    """The scene a video of this topic must contain so the viewer sees the example move: 'trace' for algorithms, 'flow' for system
    design and architecture. Only for the explainer and Remotion renderers, the ones that draw them."""
    if (spec or {}).get("renderer") not in ("explainer", "remotion"):
        return ""
    kind = " ".join(str((cat or {}).get(k) or "") for k in ("id", "label", "kicker")).lower()
    if any(w in kind for w in ("leetcode", "algorithm")):
        return "trace"
    if any(w in kind for w in ("system design", "system-design", "architecture")):
        return "flow"
    return ""


def script_problems(script, spec, cat, profile):
    """The automatic checks on a YouTube script before any reviewer sees it. spec: platforms.video_spec(...)."""
    problems = []
    scenes = script.get("scenes") or []
    text = script.get("text") or ""
    words = len(text.split())
    target, hi = spec["target_seconds"], spec["max_words"]
    lo = int(hi * 0.7)
    wps = spec.get("wps", 2.5)
    if words > int(hi * 1.1):
        problems.append(f"the narration is {words} words: about {words / wps:.0f} seconds, but this {spec['format']} video "
                        f"should run about {target} seconds ({hi} words at most). Cut {words - hi} words")
    elif words < lo:
        problems.append(f"the narration is only {words} words: about {words / wps:.0f} seconds, but this video should "
                        f"run about {target} seconds ({lo}-{hi} words)")
    mn, mx = (3, 24) if spec["format"] == "short" else (4, 40)
    if not mn <= len(scenes) <= mx:
        problems.append(f"{len(scenes)} scenes: a {spec['format']} video needs {mn}-{mx}")
    for i, sc in enumerate(scenes, 1):
        if sc.get("layout") not in SCENE_LAYOUTS:
            problems.append(f"scene {i}: layout must be one of {SCENE_LAYOUTS}")
        if not (sc.get("narration") or "").strip():
            problems.append(f"scene {i} has no narration")
        if sc.get("layout") == "code":
            code_problem = check_code(sc.get("code") or "", sc.get("language") or "")
            if code_problem:
                problems.append(f"scene {i}: {code_problem}")
        elif sc.get("layout") == "points" and not 1 <= len(sc.get("items") or []) <= 5:
            problems.append(f"scene {i}: 'points' needs 1-5 items")
        elif sc.get("layout") == "trace":
            from .render.scenes import trace_problem
            bad = trace_problem(sc)
            if bad:
                problems.append(f"scene {i}: {bad}")
        elif sc.get("layout") in ("diagram", "flow"):
            from .render.scenes import ICONS, parse_edge, split_node
            nodes = [n for n in sc.get("nodes") or [] if split_node(n)[0]]
            edges = sc.get("edges") or []
            labels = [split_node(n)[0] for n in nodes]
            if not 2 <= len(nodes) <= 6 or len(set(n.lower() for n in labels)) != len(nodes) or any(len(n) > 18 for n in labels):
                problems.append(f"scene {i}: a diagram needs 2-6 different boxes with labels of at most 18 characters")
            elif any(split_node(n)[1] and split_node(n)[1] not in ICONS for n in nodes):
                problems.append(f"scene {i}: an icon after | must be one of {', '.join(ICONS)}")
            elif not 1 <= len(edges) <= 8:
                problems.append(f"scene {i}: a diagram needs 1-8 arrows")
            else:
                bad = [e for e in edges if not parse_edge(e, nodes)]
                if bad:
                    problems.append(f"scene {i}: arrow {bad[0]!r} must be 'Box > Other box' using the exact box labels")
        elif sc.get("layout") in ("title", "statement") and not (sc.get("on_screen") or "").strip():
            problems.append(f"scene {i}: write the on-screen text")
    for i, sc in enumerate(scenes, 1):   # what the voice would have to guess at (code, symbols with no spoken form, odd words, lone letters)
        for msg in speech.problems(sc.get("narration") or ""):
            problems.append(f"scene {i}: {msg}")
    last = (scenes[-1].get("narration") or "").lower() if scenes else ""
    if spec.get("outro") and scenes and not (all(w in last for w in ("like", "comment")) and ("share" in last or "subscribe" in last)):
        problems.append("the last scene must be the closing scene: only the closing line asking the viewer to like, comment and "
                        f"share, said warmly in your own words if you keep its meaning: {spec['outro']!r}")
    if spec.get("outro") and len(scenes) > 1 and any(w in (scenes[-2].get("narration") or "").lower() for w in ("like and subscribe", "like, comment")):
        problems.append("the closing line belongs only in the last scene, on its own: take it out of the scene before")
    need = needed_visual(spec, cat)
    if need and len(scenes) >= 3 and not any(sc.get("layout") == need for sc in scenes):
        problems.append({"trace": "this is an algorithm video: add a 'trace' scene that walks the example array (cells) with moving "
                                  "pointers, the arithmetic of each step in its note, ending with the answer found",
                         "flow": "this is a system-design video: add a 'flow' scene that follows one concrete request through the "
                                 "boxes, with the real data (GET /cart?user=42, 3 items) as each arrow's label"}[need])
    joined = " ".join((sc.get("narration") or "") for sc in scenes)
    if scenes and norm(joined) != norm(text):
        problems.append("'text' must be the scenes' narration, in order: it is what the voice reads")
    title = (script.get("title") or "").strip()
    if not 10 <= len(title) <= YOUTUBE_TITLE_MAX:
        problems.append(f"the title is {len(title)} characters; YouTube allows {YOUTUBE_TITLE_MAX} and a good one has 10-70")
    desc = script.get("description") or ""
    if not 40 <= len(desc) <= YOUTUBE_DESC_MAX:
        problems.append(f"the description is {len(desc)} characters; write 40-{YOUTUBE_DESC_MAX}")
    tags = script.get("tags") or []
    if not 3 <= len(tags) <= 15 or sum(len(t) + 1 for t in tags) > YOUTUBE_TAGS_MAX or any(len(t) > 30 or "," in t for t in tags):
        problems.append(f"tags: 3-15 short tags (under 30 characters, no commas), {YOUTUBE_TAGS_MAX} characters in all")
    thumb = (script.get("thumbnail_text") or "").strip()
    if not 2 <= len(thumb) <= 30:
        problems.append("thumbnail_text must be 2-30 characters")
    everything = "\n".join([text, title, desc, thumb, " ".join(tags)])
    m = PLACEHOLDER.search(everything)
    if m:
        problems.append(f"remove the placeholder {m.group()!r}")
    bad = [b for b in profile.get("blocklist", []) if re.search(r"\b" + re.escape(b) + r"\b", everything, re.I)]
    if bad:
        problems.append(f"contains blocked phrase(s): {bad}")
    slop = [x for x in SLOP if x in text.lower()]
    if slop:
        problems.append(f"remove hype phrases: {slop}")
    if "**" in text or "`" in text or re.search(r"(?m)^#{1,6} ", text):
        problems.append("the narration is read aloud: no markdown (**, #, backticks)")
    if re.search(r"<\s*break|\[\s*(long )?pause", text, re.I):
        problems.append("no [pause] or <break> tags: write full stops, commas and a '...' for a beat; the app adds the pauses")
    for i, sc in enumerate(scenes, 1):   # a voice trips on long sentences, and a learner on long explanations
        for s in re.split(r"(?<=[.!?])\s+", (sc.get("narration") or "").replace("...", "\u2026")):
            n = len(s.split())
            if n > SENTENCE_MAX:
                problems.append(f"scene {i}: a sentence of {n} words ({' '.join(s.split()[:6])}...): split it, spoken "
                                f"sentences are at most 25 words")
                break
    if URL.search(text):
        problems.append("do not read a web address aloud: put links in the description")
    if re.search(r"\b(hey guys|what's up guys|smash that|don't forget to (like|subscribe))\b", text, re.I):
        problems.append("cut the filler opener / begging for likes: start with the problem or the result")
    about = norm(" ".join(profile.get("about", [])))
    for m in INVENTED.finditer(text):
        if norm(m.group()) not in about:
            problems.append(f"'{m.group()}' claims personal experience that is not in profile.about; rephrase as advice")
            break
    return problems


def number_problems(text, media_text, verified):
    corpus = " ".join([s["page"] for s in verified if s["verified"]] +
                      [norm(e) for s in verified for e in s["excerpts"]])
    known = {bare(t) for t in significant_numbers(corpus)}
    missing = [t for t in dict.fromkeys(significant_numbers(text + "\n" + media_text)) if bare(t) not in known]
    hard = [t for t in missing if "%" in t or "$" in t or len(re.sub(r"\D", "", t)) >= 3]
    return [f"these numbers are not in any verified source: {hard} (remove them or quote the source)"] if hard else []


def poster_number_problems(post_text, poster_text):
    """Numbers on the poster must also be in the post (the Editor flags a mismatch as a red flag)."""
    in_post = {bare(t) for t in significant_numbers(post_text)}
    extra = [t for t in dict.fromkeys(significant_numbers(poster_text)) if bare(t) not in in_post]
    return [f"the poster shows numbers the post does not: {extra}; use only the post's figures"] if extra else []


def link_problems(text, first_comment, verified):
    allowed = {norm_url(s["url"]) for s in verified if s["verified"]}
    stray = [u for u in URL.findall((text or "") + "\n" + (first_comment or "")) if norm_url(u) not in allowed]
    return [f"these links are not verified sources: {stray}"] if stray else []


def repeat_problem(topic, text, history):
    key = norm(topic)
    for h in history[-60:]:
        if key and (key == norm(h.get("topic", "")) or
                    difflib.SequenceMatcher(None, key, norm(h.get("topic", ""))).ratio() > 0.85):
            return f"topic repeats '{h.get('topic')}' ({h.get('date', '?')})"
        if text and difflib.SequenceMatcher(None, norm(text)[:500], norm(h.get("text", ""))[:500]).ratio() > 0.6:
            return f"text is too similar to the post '{h.get('topic')}' ({h.get('date', '?')})"
    return None


def check_code(code, lang):
    """'' = parses, None = not checked for this language, otherwise the error."""
    lang = (lang or "").lower()
    try:
        if lang == "python":
            ast.parse(code)
        elif lang == "json":
            json.loads(code)
        elif lang == "bash":
            r = subprocess.run(["bash", "-n"], input=code, text=True, capture_output=True, timeout=10)
            if r.returncode:
                return r.stderr.strip()[:200]
        else:
            return None
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:160]}"
    return ""
