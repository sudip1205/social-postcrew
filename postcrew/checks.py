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


def source_problems(verified, research_mode, max_age_days=None, today=None):
    problems = []
    good = [s for s in verified if s["verified"]]
    if research_mode == "required" and not good:
        detail = "; ".join(f"{s['url']}: {s.get('error', '')}" for s in verified) or "no sources given"
        problems.append(f"need at least one verified https source with a verbatim quote ({detail})")
    if research_mode == "required" and max_age_days and good:
        today = today or date.today()
        fresh = False
        for s in good:
            try:
                d = datetime.strptime(s["published"][:10], "%Y-%m-%d").date()
                fresh = fresh or (today - timedelta(days=max_age_days) <= d <= today)
            except ValueError:
                pass
        if not fresh:
            problems.append(f"need a verified source published within the last {max_age_days} days "
                            f"(set 'published' to its YYYY-MM-DD date)")
    return problems


# ---------- text ----------
def text_problems(text, cat, profile, first_comment=""):
    problems = []
    n = len(text)
    if not cat["min_chars"] <= n <= cat["max_chars"]:
        problems.append(f"length is {n} characters; this category needs {cat['min_chars']}-{cat['max_chars']}")
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


def number_problems(text, media_text, verified):
    corpus = " ".join([s["page"] for s in verified if s["verified"]] +
                      [norm(e) for s in verified for e in s["excerpts"]])
    known = {bare(t) for t in significant_numbers(corpus)}
    missing = [t for t in dict.fromkeys(significant_numbers(text + "\n" + media_text)) if bare(t) not in known]
    hard = [t for t in missing if "%" in t or "$" in t or len(re.sub(r"\D", "", t)) >= 3]
    return [f"these numbers are not in any verified source: {hard} (remove them or quote the source)"] if hard else []


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
