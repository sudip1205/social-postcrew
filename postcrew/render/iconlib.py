"""Icons and cliparts for video graphics: free, offline, permissively licensed (Iconify sets installed with the Remotion project).

  lucide              ISC     simple line icons: concepts, devices, actions     (monochrome: drawn in the video's colours)
  logos               CC0     full-colour logos of tools and products           (Redis, PostgreSQL, Kafka, Nginx, Docker...)
  simple-icons        CC0     one-colour brand marks                            (anything not in logos)
  fluent-emoji-flat   MIT     full-colour flat cliparts                         (a lock, a warning sign, a rocket, a stopwatch...)

An icon is named "set:name" (lucide:database, logos:redis, fluent-emoji-flat:locked). `search` finds candidates for a word,
`get` gives the SVG, and the renderers draw it. The older one-word hints (client, database, cache...) still work.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "remotion" / "node_modules" / "@iconify-json"
SETS = ("lucide", "logos", "simple-icons", "fluent-emoji-flat")
MONO = {"lucide", "simple-icons"}   # drawn in the page's colour; the others keep their own colours
_CACHE = {}

LEGACY = {"client": "lucide:monitor", "phone": "lucide:smartphone", "server": "lucide:server", "database": "lucide:database",
          "cache": "lucide:zap", "queue": "lucide:list-ordered", "gateway": "lucide:door-open", "user": "lucide:user",
          "cloud": "lucide:cloud", "lock": "lucide:lock", "key": "lucide:key-round", "file": "lucide:file-text",
          "terminal": "lucide:terminal", "globe": "lucide:globe", "service": "lucide:box", "generic": "lucide:box"}
# how people say a thing in a diagram -> words to look for in the sets
SYNONYMS = {"client": ["monitor", "laptop"], "browser": ["globe", "app-window"], "load balancer": ["network", "split"], "balancer": ["network"],
            "app server": ["server"], "app servers": ["server"], "web server": ["server"], "api": ["webhook", "plug"], "gateway": ["door-open"],
            "cache": ["zap"], "database": ["database"], "db": ["database"], "storage": ["hard-drive", "database"], "queue": ["list-ordered"],
            "worker": ["cog"], "user": ["user"], "users": ["users"], "visitor": ["user"], "request": ["arrow-right-left"], "id generator": ["hash", "key-round"],
            "counter": ["hash"], "cdn": ["globe"], "dns": ["globe"], "firewall": ["shield"], "token": ["key-round"], "password": ["lock"],
            "hash": ["hash"], "encryption": ["lock"], "secret": ["key-round"], "mobile": ["smartphone"], "phone": ["smartphone"],
            "click": ["mouse-pointer-click"], "counter": ["hash"], "shortener": ["link"], "link": ["link"], "url": ["link"], "redirect": ["corner-up-right"]}
STOP = {"the", "a", "an", "of", "to", "and", "for", "in", "on", "with", "your", "our", "is", "it"}


def available():
    return all((ROOT / s / "icons.json").exists() for s in SETS)


def _load(name):
    if name not in _CACHE:
        path = ROOT / name / "icons.json"
        _CACHE[name] = json.loads(path.read_text()) if path.exists() else {"icons": {}, "aliases": {}, "width": 24, "height": 24}
    return _CACHE[name]


def exists(icon_id):
    s, _, n = str(icon_id).partition(":")
    if s not in SETS:
        return False
    data = _load(s)
    return n in data["icons"] or n in (data.get("aliases") or {})


def get(icon_id):
    """{"id", "body", "w", "h", "color"} of an icon ("set:name", or an older hint such as "database"), or None when it does not exist."""
    icon_id = LEGACY.get(str(icon_id or "").strip().lower(), str(icon_id or "").strip())
    s, _, n = icon_id.partition(":")
    if s not in SETS:
        return None
    data = _load(s)
    seen = 0
    while n in (data.get("aliases") or {}) and n not in data["icons"] and seen < 5:   # an alias points at the real icon
        n, seen = data["aliases"][n]["parent"], seen + 1
    ic = data["icons"].get(n)
    if not ic:
        return None
    return {"id": f"{s}:{n}", "body": ic["body"], "w": ic.get("width", data.get("width", 24)), "h": ic.get("height", data.get("height", 24)),
            "color": s not in MONO}


def _words(text):
    return [w for w in re.findall(r"[a-z0-9]+", str(text).lower()) if w not in STOP]


def search(query, limit=6, sets=SETS):
    """Icons for a label or a concept, best first: [{"id", "set", "name"}]. Tool and product names find their logo; concepts find a line icon
    or a clipart. Matching is by the words of the icon's name (database matches database, database-zap, ...)."""
    q = str(query).lower().strip()
    toks = _words(q)
    wanted = list(SYNONYMS.get(q, [])) + [w for w in toks if w not in SYNONYMS.get(q, [])]
    for t in toks:
        wanted += [x for x in SYNONYMS.get(t, []) if x not in wanted]
    scored = []
    for s in sets:
        data = _load(s)
        names = list(data["icons"]) + list((data.get("aliases") or {}))
        for n in names:
            parts = n.split("-")
            sc = 0
            for rank, w in enumerate(wanted):
                if n == w:
                    sc = max(sc, 100 - rank)
                elif w in parts:
                    sc = max(sc, 60 - rank)
                elif len(w) >= 4 and n.startswith(w):
                    sc = max(sc, 40 - rank)
            if not sc:
                continue
            sc += {"logos": 12, "lucide": 8, "fluent-emoji-flat": 4, "simple-icons": 0}[s]   # a product logo beats a line icon beats a mono mark
            if s == "lucide" and any(w in SYNONYMS.get(q, []) for w in [n]):
                sc += 20
            scored.append((sc, -len(n), s, n))
    scored.sort(reverse=True)
    out, seen = [], set()
    for sc, _, s, n in scored:
        key = (s, n)
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": f"{s}:{n}", "set": s, "name": n})
        if len(out) >= limit:
            break
    return out


def auto(label):
    """The best single icon id for a label, or '' when nothing fits well (the box is then drawn without an icon)."""
    hits = search(label, 1)
    return hits[0]["id"] if hits else ""


def svg(icon_id):
    """What the renderers draw: {"body", "w", "h", "color"} (the icon's SVG inner markup), or None."""
    ic = get(icon_id)
    return {k: ic[k] for k in ("body", "w", "h", "color")} if ic else None
