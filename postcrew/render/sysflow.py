"""System-flow animation: real components, real connections, and messages that travel between them.

A spec (see SCHEMA) lists the components of a system (browser, API gateway, auth server, database, cache, queue,
LLM, agent ...) and the messages they send each other, in order, in one or two scenes (for example "without" and
"with" a fix). The renderer draws:

  * every component as a card with its own icon, placed on a grid so the connections stay short and never run
    through another card
  * a connection for every pair that talks, with a lane per direction when both directions are used
  * a packet (a pill with the message label, coloured by kind) that travels along the connection
  * the component's state changing when a message arrives (cache: user:42, token: valid 5m ...), and a status
    badge (ok, denied, warning, waiting)
  * an "on the wire" log with the payload of the last messages, and a caption that narrates the current step

Pillow draws the frames and ffmpeg encodes them (1080x1350, H.264, 30 fps), like the other animations. The
static layers are drawn once at 2x and reused; each frame only draws what moves.
"""
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from ..brief import COMPONENT_KINDS, STEP_KINDS, slug
from .theme import (BG, BORDER, CARD, CARD_HI, CODE_BG, CORAL, CREAM, GOLD, H, HL_LINE, INK, MUTED, RULE, TEAL, W,
                    Painter, footer, pill, text_width, wrap)

FPS = 30
MIN_SECONDS, MAX_SECONDS = 15.0, 45.0
MAX_SYSTEMS, MAX_STEPS = 8, 12

GREEN, BLUE, VIOLET, PINK = "#5fd38d", "#7fb2ff", "#b39dff", "#f08fd0"
EDGE_DIM, EDGE_ON, STRIP = "#2c4a70", "#4f7fb0", "#0f2840"

# the diagram region of the 1080x1350 frame, and where card centres may go inside it
DY, DH = 286, 674
AREA = (60, 62, 1020, 668)
NODE_H = 150
NODE_W2, NODE_W3 = 270, 226      # card width with two columns / with three: wider gaps for the packets
CAP_Y, CAP_H = 960, 128
LOG_Y, LOG_H = 1100, 140

ACCENT = {"user": TEAL, "attacker": CORAL, "browser": TEAL, "mobile": TEAL, "service": BLUE, "api-gateway": GOLD,
          "load-balancer": GOLD, "firewall": GOLD, "cdn": GOLD, "database": VIOLET, "cache": VIOLET, "queue": VIOLET,
          "storage": VIOLET, "idp": GREEN, "vault": GREEN, "llm": PINK, "agent": PINK, "worker": BLUE,
          "external": "#c4cfdf"}
KIND_COLOR = {"request": TEAL, "response": GOLD, "data": VIOLET, "token": GREEN, "event": BLUE, "attack": CORAL,
              "error": CORAL}
STATUS_COLOR = {"ok": GREEN, "deny": CORAL, "warn": GOLD, "wait": BLUE}
STATUSES = list(STATUS_COLOR) + ["clear"]


class SysflowError(RuntimeError):
    pass


# ------------------------------------------------------------------ the spec the Visual Designer writes
STEP = {
    "type": "object",
    "properties": {
        "from": {"type": "string", "description": "id of the component that sends (same id = it works on its own)"},
        "to": {"type": "string", "description": "id of the component that receives"},
        "label": {"type": "string", "description": "short name of the message, max 16 chars, shown on the packet"},
        "kind": {"type": "string", "enum": STEP_KINDS},
        "payload": {"type": "string", "description": "the real thing on the wire, max 80 chars, e.g. 'POST /refund'"},
        "caption": {"type": "string", "description": "one plain sentence narrating this step, max 120 chars"},
        "state": {"type": "array", "maxItems": 2, "items": {
            "type": "object", "properties": {"node": {"type": "string"}, "text": {"type": "string"}},
            "required": ["node", "text"], "additionalProperties": False},
            "description": "a component's visible state after this message, text max 18 chars (cache: user:42)"},
        "status": {"type": "array", "maxItems": 2, "items": {
            "type": "object", "properties": {"node": {"type": "string"}, "value": {"type": "string", "enum": STATUSES}},
            "required": ["node", "value"], "additionalProperties": False}},
    },
    "required": ["from", "to", "label", "kind", "caption"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "kicker": {"type": "string"},
        "title": {"type": "string", "description": "max 70 chars"},
        "subtitle": {"type": "string", "description": "max 100 chars"},
        "intro": {"type": "string", "description": "caption while the components appear, max 110 chars"},
        "takeaway": {"type": "string", "description": "the one-line lesson shown at the end, max 110 chars"},
        "systems": {"type": "array", "minItems": 2, "maxItems": MAX_SYSTEMS, "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"}, "label": {"type": "string", "description": "max 24 chars"},
                "kind": {"type": "string", "enum": COMPONENT_KINDS},
                "note": {"type": "string", "description": "what it is, max 24 chars"},
                "col": {"type": "integer", "minimum": 0, "maximum": 2},
                "row": {"type": "integer", "minimum": 0, "maximum": 2}},
            "required": ["id", "label", "kind", "note"], "additionalProperties": False}},
        "scenes": {"type": "array", "minItems": 1, "maxItems": 2, "items": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "max 50 chars; empty if there is one scene"},
                           "steps": {"type": "array", "minItems": 1, "maxItems": 10, "items": STEP}},
            "required": ["title", "steps"], "additionalProperties": False}},
    },
    "required": ["title", "subtitle", "intro", "takeaway", "systems", "scenes"],
    "additionalProperties": False,
}


def _pairs(v, field):
    """[(node, value)] from either the list the model writes ([{node, text}]) or the dict clean() produces."""
    if isinstance(v, dict):
        return list(v.items())
    return [(x.get("node", ""), x.get(field)) for x in (v or []) if isinstance(x, dict)]


def clean(spec):
    """A copy of the spec with ids resolved, state/status turned into dicts, and defaults filled in."""
    systems = []
    for s in spec.get("systems", []):
        label = str(s.get("label") or s.get("id") or "").strip()
        systems.append({"id": slug(s.get("id") or label), "label": label, "kind": s.get("kind") or "service",
                        "note": str(s.get("note") or "").strip(), "col": s.get("col"), "row": s.get("row")})
    names = {}
    for s in systems:
        names[s["id"]] = s["id"]
        names[slug(s["label"])] = s["id"]

    def ref(x):
        x = slug(x)
        return names.get(x, x)
    scenes = []
    for sc in spec.get("scenes", []):
        steps = []
        for st in sc.get("steps", []):
            steps.append({
                "from": ref(st.get("from", "")), "to": ref(st.get("to", "")),
                "label": re.sub(r"^\s*(?:step\s*)?\d+\s*[.):\-]\s*", "", str(st.get("label") or "")).strip(), "kind": st.get("kind") or "request",
                "payload": str(st.get("payload") or "").strip(), "caption": str(st.get("caption") or "").strip(),
                "state": {ref(n): str(v).strip() for n, v in _pairs(st.get("state"), "text")},
                "status": {ref(n): v for n, v in _pairs(st.get("status"), "value")}})
        scenes.append({"title": str(sc.get("title") or "").strip(), "steps": steps})
    return {"kicker": str(spec.get("kicker") or "SYSTEM FLOW").strip().upper()[:28],
            "title": str(spec.get("title") or "").strip(), "subtitle": str(spec.get("subtitle") or "").strip(),
            "intro": str(spec.get("intro") or "").strip(), "takeaway": str(spec.get("takeaway") or "").strip(),
            "systems": systems, "scenes": scenes}


# ------------------------------------------------------------------ layout
def _flat(spec):
    return [st for sc in spec["scenes"] for st in sc["steps"]]


def _order(spec):
    seen = []
    for st in _flat(spec):
        for x in (st["from"], st["to"]):
            if x not in seen:
                seen.append(x)
    return seen + [s["id"] for s in spec["systems"] if s["id"] not in seen]


def _layers(order, pairs):
    adj = {o: set() for o in order}
    for a, b in pairs:
        if a in adj and b in adj and a != b:
            adj[a].add(b)
            adj[b].add(a)
    layer = {}
    for root in order:
        if root in layer:
            continue
        layer[root] = 0
        q = [root]
        while q:
            u = q.pop(0)
            for v in sorted(adj[u], key=order.index):
                if v not in layer:
                    layer[v] = layer[u] + 1
                    q.append(v)
    return layer


def _candidates(order, layer):
    n = len(order)
    out = []
    for cols in (2, 3):
        cells = {}
        for i, o in enumerate(order):
            r, c = divmod(i, cols)
            cells[o] = (c if r % 2 == 0 else cols - 1 - c, r)
        if max(r for _, r in cells.values()) <= 2:
            out.append((f"snake{cols}", cells, 0.0 if (cols == 2) == (n <= 6) else 3.0))   # two wide columns when they hold it
    groups = {}
    for o in order:
        groups.setdefault(layer[o], []).append(o)
    L = len(groups)
    biggest = max(len(g) for g in groups.values())
    if L <= 3 and biggest <= 3:
        for name, flip in (("layer-cols", False), ("layer-rows", True)):
            cells = {}
            for li, g in sorted(groups.items()):
                for i, o in enumerate(g):
                    pos = (i - (len(g) - 1) / 2)
                    cells[o] = (pos, li) if flip else (li, pos)
            wide = len({c for c, _ in cells.values()}) > 2 and n <= 6
            out.append((name, cells, 0.4 + (3.0 if wide else 0.0)))
    cells = {}
    for i, o in enumerate(order):                # fill top to bottom, three rows per column
        c, r = divmod(i, 3)
        cells[o] = (c, r if c % 2 == 0 else 2 - r)
    if max(c for c, _ in cells.values()) <= 2:
        out.append(("columns", cells, 0.8 + (3.0 if (max(c for c, _ in cells.values()) > 1 and n <= 6) else 0.0)))
    return out


@dataclass
class Layout:
    centers: dict
    px: float
    py: float
    w: float = NODE_W2
    h: float = NODE_H
    collisions: list = field(default_factory=list)
    name: str = ""


def _centers(cells):
    cs = [c for c, _ in cells.values()]
    rs = [r for _, r in cells.values()]
    span_c, span_r = max(cs) - min(cs) + 1, max(rs) - min(rs) + 1
    px, py = min(400.0, (AREA[2] - AREA[0]) / span_c), min(222.0, (AREA[3] - AREA[1]) / span_r)
    mc, mr = (max(cs) + min(cs)) / 2, (max(rs) + min(rs)) / 2
    x0, y0 = (AREA[0] + AREA[2]) / 2, (AREA[1] + AREA[3]) / 2
    return {o: (x0 + (c - mc) * px, y0 + (r - mr) * py) for o, (c, r) in cells.items()}, px, py, \
        NODE_W2 if span_c <= 2 else NODE_W3


def _rect(lay, c, pad=0):
    return (c[0] - lay.w / 2 + pad, c[1] - lay.h / 2 + pad, c[0] + lay.w / 2 - pad, c[1] + lay.h / 2 - pad)


def _routes(lay, a, b, o):
    """Every orthogonal way to run a connection from card a to card b, simplest first."""
    (ax, ay), (bx, by) = lay.centers[a], lay.centers[b]
    dx, dy = bx - ax, by - ay
    w2, h2 = lay.w / 2, lay.h / 2
    sx_, sy_ = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    out = []
    if abs(dy) < 1:
        return [[(ax + sx_ * w2, ay + o), (bx - sx_ * w2, by + o)]]
    if abs(dx) < 1:
        return [[(ax + o, ay + sy_ * h2), (bx + o, by - sy_ * h2)]]
    jx = ax + sx_ * (w2 + max(14.0, (lay.px - lay.w) / 2))
    jy = ay + sy_ * (h2 + max(14.0, (lay.py - lay.h) / 2))
    out.append([(ax + sx_ * w2, ay + o), (bx - o, ay + o), (bx - o, by - sy_ * h2)])                  # across, then down
    out.append([(ax + o, ay + sy_ * h2), (ax + o, by + o), (bx - sx_ * w2, by + o)])                  # down, then across
    out.append([(ax + sx_ * w2, ay + o), (jx + o, ay + o), (jx + o, by + o), (bx - sx_ * w2, by + o)])   # jog in the column gap
    out.append([(ax + o, ay + sy_ * h2), (ax + o, jy + o), (bx + o, jy + o), (bx + o, by - sy_ * h2)])   # jog in the row gap
    return out


def _hits(path, rects):
    bad = []
    for (x1, y1), (x2, y2) in zip(path, path[1:]):
        sb = (min(x1, x2) - 1, min(y1, y2) - 1, max(x1, x2) + 1, max(y1, y2) + 1)
        for name, r in rects.items():
            if sb[0] < r[2] and sb[2] > r[0] and sb[1] < r[3] and sb[3] > r[1]:
                bad.append(name)
    return bad


def link_path(lay, a, b, o=0.0):
    """The connection from card a to card b: the route that avoids the other cards, with the fewest bends.
    o shifts it sideways, for the second lane of a pair that talks both ways. Both directions of a pair share one
    route (the one chosen for the alphabetical order), so their lanes run side by side."""
    if a > b:
        return link_path(lay, b, a, o)[::-1]
    others = {k: _rect(lay, c, 6) for k, c in lay.centers.items() if k not in (a, b)}
    best = None
    for n, path in enumerate(_routes(lay, a, b, o)):
        cost = len(_hits(path, others)) * 1000 + (len(path) - 2) * 8 + n + path_len(path) * .01
        if best is None or cost < best[0]:
            best = (cost, path)
    return best[1]


def pairs_of(spec):
    out = []
    for st in _flat(spec):
        if st["from"] != st["to"]:
            out.append((st["from"], st["to"]))
    return out


def _cross(p, q):
    """How badly two orthogonal polylines get in each other's way: 1 per crossing, 5 per shared stretch."""
    n = 0
    for (a1, a2) in zip(p, p[1:]):
        for (b1, b2) in zip(q, q[1:]):
            ah, bh = abs(a1[1] - a2[1]) < 1, abs(b1[1] - b2[1]) < 1
            if ah != bh:
                h, v = ((a1, a2), (b1, b2)) if ah else ((b1, b2), (a1, a2))
                if min(h[0][0], h[1][0]) < v[0][0] < max(h[0][0], h[1][0]) and \
                        min(v[0][1], v[1][1]) < h[0][1] < max(v[0][1], v[1][1]):
                    n += 1
            elif ah and abs(a1[1] - b1[1]) < 3 and min(a1[0], a2[0]) < max(b1[0], b2[0]) and min(b1[0], b2[0]) < max(a1[0], a2[0]):
                n += 5
            elif not ah and abs(a1[0] - b1[0]) < 3 and min(a1[1], a2[1]) < max(b1[1], b2[1]) and min(b1[1], b2[1]) < max(a1[1], a2[1]):
                n += 5
    return n


def _evaluate(spec, cells, name=""):
    centers, px, py, w = _centers(cells)
    lay = Layout(centers, px, py, w, NODE_H, [], name)
    rects = {o: _rect(lay, c, 5) for o, c in centers.items()}
    cost, paths = 0.0, []
    for a, b in sorted({tuple(sorted(p)) for p in pairs_of(spec)}):
        path = link_path(lay, a, b)
        paths.append(path)
        cost += path_len(path) * 0.01 + (len(path) - 2) * 6
        for hit in set(_hits(path, {k: r for k, r in rects.items() if k not in (a, b)})):
            lay.collisions.append(f"the connection {a} - {b} runs through {hit}")
            cost += 1000
    for i, p in enumerate(paths):
        for q in paths[i + 1:]:
            cost += 25 * _cross(p, q)
    return lay, cost


def choose_layout(spec):
    """The positions the Visual Designer gave (col/row for every component), or the best automatic arrangement."""
    ids = [s["id"] for s in spec["systems"]]
    given = {s["id"]: (s["col"], s["row"]) for s in spec["systems"] if s.get("col") is not None and s.get("row") is not None}
    if len(given) == len(ids):
        return _evaluate(spec, given, "given")[0]
    order = _order(spec)
    layer = _layers(order, pairs_of(spec))
    best = None
    for name, cells, pref in _candidates(order, layer):
        lay, cost = _evaluate(spec, cells, name)
        cost += pref
        if best is None or cost < best[0]:
            best = (cost, lay)
    if best is None:
        raise SysflowError("could not place the components on the grid; use at most 8 and give col/row for each")
    return best[1]


# ------------------------------------------------------------------ checking the spec
def validate_spec(raw):
    """Problems that would make the animation wrong or unreadable; [] = fine. The Visual Designer gets these."""
    spec = clean(raw)
    out = []
    ids = [s["id"] for s in spec["systems"]]
    if not 2 <= len(ids) <= MAX_SYSTEMS:
        out.append(f"use 2-{MAX_SYSTEMS} components (got {len(ids)})")
    if len(set(ids)) != len(ids):
        out.append("component ids must be unique")
    for s in spec["systems"]:
        if s["kind"] not in COMPONENT_KINDS:
            out.append(f"component {s['label']!r}: kind must be one of {COMPONENT_KINDS}")
        if not s["label"] or len(s["label"]) > 24:
            out.append(f"component label {s['label']!r} must be 1-24 characters")
        if len(s["note"]) > 24:
            out.append(f"note of {s['label']!r} is {len(s['note'])} characters; keep it under 24")
    for key, lim in (("title", 70), ("subtitle", 100), ("intro", 110), ("takeaway", 110)):
        if not spec[key]:
            out.append(f"{key} is empty")
        elif len(spec[key]) > lim:
            out.append(f"{key} is {len(spec[key])} characters; keep it under {lim}")
    if spec["title"] and len(wrap(spec["title"], "bold", 50, 960)) > 2:
        out.append("the title needs more than two lines; shorten it")
    steps = _flat(spec)
    if not 3 <= len(steps) <= MAX_STEPS:
        out.append(f"use 3-{MAX_STEPS} steps in total (got {len(steps)})")
    if not 1 <= len(spec["scenes"]) <= 2:
        out.append("use one or two scenes")
    if len(spec["scenes"]) > 1 and any(not sc["title"] for sc in spec["scenes"]):
        out.append("with two scenes each needs a title, for example 'Without PKCE' and 'With PKCE'")
    used, changes = set(), 0
    for n, st in enumerate(steps, 1):
        where = f"step {n}"
        for end in ("from", "to"):
            if st[end] not in ids:
                out.append(f"{where}: '{st[end]}' is not a component id ({', '.join(ids)})")
        used |= {st["from"], st["to"]}
        if st["kind"] not in STEP_KINDS:
            out.append(f"{where}: kind must be one of {STEP_KINDS}")
        if not st["label"] or len(st["label"]) > 16:
            out.append(f"{where}: label must be 1-16 characters (got {len(st['label'])}): it is the text on the packet")
        if len(st["payload"]) > 80:
            out.append(f"{where}: payload is {len(st['payload'])} characters; keep it under 80")
        if not st["caption"] or len(st["caption"]) > 120:
            out.append(f"{where}: caption must be 1-120 characters (got {len(st['caption'])})")
        for node, text in st["state"].items():
            changes += 1
            if node not in ids:
                out.append(f"{where}: state refers to unknown component '{node}'")
            if not 1 <= len(text) <= 18:
                out.append(f"{where}: state text {text!r} must be 1-18 characters")
        for node, val in st["status"].items():
            changes += 1
            if node not in ids:
                out.append(f"{where}: status refers to unknown component '{node}'")
            if val not in STATUSES:
                out.append(f"{where}: status must be one of {STATUSES}")
    for i in ids:
        if i not in used:
            out.append(f"component '{i}' never sends or receives anything; use it in a step or remove it")
    if steps and changes < 2:
        out.append("no component changes state: show at least two state or status changes (cache: user:42, "
                   "token: valid 5m, access denied...) so the animation shows the system working, not only arrows")
    cols = [s for s in spec["systems"] if s.get("col") is not None or s.get("row") is not None]
    if cols and len(cols) != len(spec["systems"]):
        out.append("give col and row for every component, or for none")
    for s in cols:
        if not (isinstance(s.get("col"), int) and isinstance(s.get("row"), int) and 0 <= s["col"] <= 2 and 0 <= s["row"] <= 2):
            out.append(f"component {s['label']!r}: col and row must be whole numbers 0-2")
    cells = [(s["col"], s["row"]) for s in cols]
    if len(set(cells)) != len(cells):
        out.append("two components share a grid cell; give each its own col/row")
    if not out and ids:
        try:
            choose_layout(spec)   # a connection that has to pass a card is routed around it, never a reason to reject
        except SysflowError as e:
            out.append(str(e))
    return out


def shown_text(raw):
    """All the words in the video, for the number check and for the Editor. Steps are numbered once across the
    scenes (the video says "STEP n OF N"), with component names, never ids."""
    s = clean(raw)
    names = {x["id"]: x["label"] for x in s["systems"]}
    parts = ["SYSTEM ANIMATION (a simplified illustration, scene by scene)", f"Title: {s['title']}",
             f"Subtitle: {s['subtitle']}", f"Intro caption: {s['intro']}",
             "Components: " + "; ".join(f"{x['label']}" + (f" ({x['note']})" if x["note"] else "") for x in s["systems"])]
    n = 0
    for sc in s["scenes"]:
        if sc["title"]:
            parts.append(f"Scene: {sc['title']}")
        for st in sc["steps"]:
            n += 1
            extra = "".join(f" [{names.get(k, k)} shows: {v}]" for k, v in {**st["state"], **st["status"]}.items())
            parts.append(f"Step {n}: {names.get(st['from'], st['from'])} to {names.get(st['to'], st['to'])}: "
                         f"{st['label']} ({st['payload']}). {st['caption']}{extra}")
    parts.append(f"Takeaway: {s['takeaway']}")
    return "\n".join(p for p in parts if p and p.strip())


def claim_text(raw):
    """The words that make claims (title, captions, state, takeaway). Payloads and packet labels show example
    protocol traffic (ports, status codes, sizes), so the number checks leave them out."""
    s = clean(raw)
    parts = [s["title"], s["subtitle"], s["intro"], s["takeaway"]]
    for sc in s["scenes"]:
        parts.append(sc["title"])
        for st in sc["steps"]:
            parts += [st["caption"], *st["state"].values()]
    return "\n".join(p for p in parts if p and p.strip())


# ------------------------------------------------------------------ drawing helpers
def mix(c1, c2, t):
    t = max(0.0, min(1.0, t))
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _b(p, box):
    return [p._sc(v) for v in box]


def pie(p, box, a0, a1, fill):
    p.d.pieslice(_b(p, box), a0, a1, fill=fill)


def arc(p, box, a0, a1, fill, width):
    p.d.arc(_b(p, box), a0, a1, fill=fill, width=max(1, int(p._sc(width))))


def stroke(p, pts, fill, width):
    p.d.line([(p._sc(x), p._sc(y)) for x, y in pts], fill=fill, width=max(1, int(p._sc(width))), joint="curve")


def circle(p, cx, cy, r, fill=None, outline=None, width=2):
    p.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=width)


def fit(text, kind, size, max_w, min_size=16):
    """Shrink the font, then cut with an ellipsis, so the text always fits. Returns (text, size)."""
    while text_width(text, kind, size) > max_w and size > min_size:
        size -= 1
    if text_width(text, kind, size) > max_w:
        while len(text) > 1 and text_width(text + "...", kind, size) > max_w:
            text = text[:-1]
        text += "..."
    return text, size


# ------------------------------------------------------------------ icons (solid, with cut-outs in the card colour)
def _i_user(p, cx, cy, s, c, d):
    circle(p, cx, cy - .2 * s, .23 * s, fill=c)
    pie(p, (cx - .42 * s, cy + .02 * s, cx + .42 * s, cy + .86 * s), 180, 360, c)


def _i_attacker(p, cx, cy, s, c, d):
    _i_user(p, cx, cy, s, c, d)
    p.rrect((cx - .2 * s, cy - .27 * s, cx + .2 * s, cy - .15 * s), r=.04 * s, fill=d)
    stroke(p, [(cx - .09 * s, cy - .23 * s), (cx - .03 * s, cy - .19 * s)], c, .05 * s)
    stroke(p, [(cx + .09 * s, cy - .23 * s), (cx + .03 * s, cy - .19 * s)], c, .05 * s)


def _i_browser(p, cx, cy, s, c, d):
    p.rrect((cx - .46 * s, cy - .36 * s, cx + .46 * s, cy + .36 * s), r=.07 * s, fill=c)
    p.rrect((cx - .41 * s, cy - .17 * s, cx + .41 * s, cy + .31 * s), r=.04 * s, fill=d)
    for k in range(3):
        circle(p, cx - .33 * s + k * .1 * s, cy - .27 * s, .026 * s, fill=d)
    for k, w in enumerate((.5, .34)):
        p.rrect((cx - .32 * s, cy - .07 * s + k * .14 * s, cx - .32 * s + w * s, cy + .0 * s + k * .14 * s), r=.02 * s, fill=c)


def _i_mobile(p, cx, cy, s, c, d):
    p.rrect((cx - .25 * s, cy - .46 * s, cx + .25 * s, cy + .46 * s), r=.07 * s, fill=c)
    p.rrect((cx - .19 * s, cy - .36 * s, cx + .19 * s, cy + .27 * s), r=.03 * s, fill=d)
    circle(p, cx, cy + .365 * s, .035 * s, fill=d)


def _i_service(p, cx, cy, s, c, d):
    for y0 in (-.4, .04):
        p.rrect((cx - .44 * s, cy + y0 * s, cx + .44 * s, cy + (y0 + .36) * s), r=.06 * s, fill=c)
        circle(p, cx + .32 * s, cy + (y0 + .18) * s, .04 * s, fill=d)
        p.rrect((cx - .34 * s, cy + (y0 + .15) * s, cx + .0 * s, cy + (y0 + .21) * s), r=.02 * s, fill=d)


def _i_gateway(p, cx, cy, s, c, d):
    p.rrect((cx - .44 * s, cy - .42 * s, cx - .27 * s, cy + .42 * s), r=.03 * s, fill=c)
    p.rrect((cx + .27 * s, cy - .42 * s, cx + .44 * s, cy + .42 * s), r=.03 * s, fill=c)
    p.rrect((cx - .44 * s, cy - .42 * s, cx + .44 * s, cy - .24 * s), r=.04 * s, fill=c)
    stroke(p, [(cx - .17 * s, cy + .08 * s), (cx + .14 * s, cy + .08 * s)], c, .07 * s)
    p.polygon([(cx + .2 * s, cy + .08 * s), (cx + .06 * s, cy - .04 * s), (cx + .06 * s, cy + .2 * s)], c)


def _i_lb(p, cx, cy, s, c, d):
    w = .07 * s
    stroke(p, [(cx - .44 * s, cy), (cx - .08 * s, cy)], c, w)
    for dy in (-.3, 0, .3):
        stroke(p, [(cx + .02 * s, cy), (cx + .22 * s, cy + dy * s), (cx + .38 * s, cy + dy * s)], c, w)
        circle(p, cx + .42 * s, cy + dy * s, .07 * s, fill=c)
    circle(p, cx - .02 * s, cy, .12 * s, fill=c)


def _i_db(p, cx, cy, s, c, d):
    light = mix(c, "#ffffff", .3)
    p.ellipse((cx - .38 * s, cy + .16 * s, cx + .38 * s, cy + .42 * s), fill=c)
    p.rrect((cx - .38 * s, cy - .28 * s, cx + .38 * s, cy + .3 * s), r=0, fill=c)
    p.ellipse((cx - .38 * s, cy - .4 * s, cx + .38 * s, cy - .14 * s), fill=light)
    for dy in (-.06, .14):
        arc(p, (cx - .38 * s, cy + (dy - .12) * s, cx + .38 * s, cy + (dy + .12) * s), 0, 180, d, .035 * s)


def _i_cache(p, cx, cy, s, c, d):
    p.rrect((cx - .42 * s, cy - .42 * s, cx + .42 * s, cy + .42 * s), r=.1 * s, fill=c)
    p.polygon([(cx + .07 * s, cy - .34 * s), (cx - .2 * s, cy + .06 * s), (cx - .02 * s, cy + .06 * s),
               (cx - .08 * s, cy + .34 * s), (cx + .2 * s, cy - .08 * s), (cx + .02 * s, cy - .08 * s)], d)


def _i_queue(p, cx, cy, s, c, d):
    for k in range(4):
        x0 = cx - .46 * s + k * .24 * s
        if k < 3:
            p.rrect((x0, cy - .24 * s, x0 + .2 * s, cy + .24 * s), r=.04 * s, fill=c)
        else:
            p.rrect((x0, cy - .24 * s, x0 + .2 * s, cy + .24 * s), r=.04 * s, outline=c, width=max(2, .04 * s))
    stroke(p, [(cx - .4 * s, cy + .4 * s), (cx + .38 * s, cy + .4 * s)], c, .05 * s)
    p.polygon([(cx + .46 * s, cy + .4 * s), (cx + .34 * s, cy + .32 * s), (cx + .34 * s, cy + .48 * s)], c)


def _i_idp(p, cx, cy, s, c, d):
    p.polygon([(cx, cy - .46 * s), (cx + .38 * s, cy - .32 * s), (cx + .38 * s, cy + .06 * s), (cx, cy + .46 * s),
               (cx - .38 * s, cy + .06 * s), (cx - .38 * s, cy - .32 * s)], c)
    circle(p, cx, cy - .1 * s, .1 * s, fill=d)
    p.polygon([(cx - .05 * s, cy - .04 * s), (cx + .05 * s, cy - .04 * s), (cx + .09 * s, cy + .2 * s),
               (cx - .09 * s, cy + .2 * s)], d)


def _i_vault(p, cx, cy, s, c, d):
    arc(p, (cx - .22 * s, cy - .46 * s, cx + .22 * s, cy + .06 * s), 180, 360, c, .09 * s)
    stroke(p, [(cx - .22 * s, cy - .2 * s), (cx - .22 * s, cy)], c, .09 * s)
    stroke(p, [(cx + .22 * s, cy - .2 * s), (cx + .22 * s, cy)], c, .09 * s)
    p.rrect((cx - .35 * s, cy - .04 * s, cx + .35 * s, cy + .44 * s), r=.06 * s, fill=c)
    circle(p, cx, cy + .14 * s, .07 * s, fill=d)
    p.rrect((cx - .025 * s, cy + .14 * s, cx + .025 * s, cy + .3 * s), r=.01 * s, fill=d)


def _i_firewall(p, cx, cy, s, c, d):
    rows = [(-.42, [(-.46, -.02), (.02, .46)]), (-.1, [(-.46, -.26), (-.22, .22), (.26, .46)]),
            (.22, [(-.46, -.02), (.02, .46)])]
    for y0, bricks in rows:
        for a, b in bricks:
            p.rrect((cx + a * s, cy + y0 * s, cx + b * s, cy + (y0 + .24) * s), r=.03 * s, fill=c)


def _i_llm(p, cx, cy, s, c, d):
    def star(x, y, r, col):
        k = r * .22
        p.polygon([(x, y - r), (x + k, y - k), (x + r, y), (x + k, y + k), (x, y + r), (x - k, y + k), (x - r, y),
                   (x - k, y - k)], col)
    star(cx - .04 * s, cy + .04 * s, .44 * s, c)
    star(cx + .34 * s, cy - .34 * s, .2 * s, mix(c, "#ffffff", .35))


def _i_agent(p, cx, cy, s, c, d):
    stroke(p, [(cx, cy - .28 * s), (cx, cy - .42 * s)], c, .05 * s)
    circle(p, cx, cy - .45 * s, .06 * s, fill=c)
    p.rrect((cx - .4 * s, cy - .28 * s, cx + .4 * s, cy + .36 * s), r=.1 * s, fill=c)
    p.rrect((cx - .48 * s, cy - .08 * s, cx - .4 * s, cy + .14 * s), r=.02 * s, fill=c)
    p.rrect((cx + .4 * s, cy - .08 * s, cx + .48 * s, cy + .14 * s), r=.02 * s, fill=c)
    for dx in (-.16, .16):
        circle(p, cx + dx * s, cy + .0 * s, .08 * s, fill=d)
    p.rrect((cx - .14 * s, cy + .2 * s, cx + .14 * s, cy + .26 * s), r=.02 * s, fill=d)


def _i_cdn(p, cx, cy, s, c, d):
    w = max(2.5, .05 * s)
    circle(p, cx, cy, .4 * s, outline=c, width=w)
    p.ellipse((cx - .17 * s, cy - .4 * s, cx + .17 * s, cy + .4 * s), outline=c, width=w)
    stroke(p, [(cx - .4 * s, cy), (cx + .4 * s, cy)], c, w)
    for dy in (-.2, .2):
        half = math.sqrt(max(.0, .4 ** 2 - dy ** 2)) * s
        stroke(p, [(cx - half, cy + dy * s), (cx + half, cy + dy * s)], c, w)


def _i_worker(p, cx, cy, s, c, d):
    pts, teeth = [], 8
    for i in range(teeth * 4):
        a = i * 2 * math.pi / (teeth * 4)
        rad = .46 * s if i % 4 in (0, 1) else .35 * s
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    p.polygon(pts, c)
    circle(p, cx, cy, .15 * s, fill=d)


def _i_storage(p, cx, cy, s, c, d):
    p.polygon([(cx - .42 * s, cy - .3 * s), (cx + .42 * s, cy - .3 * s), (cx + .32 * s, cy + .42 * s),
               (cx - .32 * s, cy + .42 * s)], c)
    p.ellipse((cx - .42 * s, cy - .4 * s, cx + .42 * s, cy - .2 * s), fill=mix(c, "#ffffff", .3))


def _i_external(p, cx, cy, s, c, d):
    p.rrect((cx - .44 * s, cy - .02 * s, cx + .44 * s, cy + .36 * s), r=.18 * s, fill=c)
    circle(p, cx - .16 * s, cy - .08 * s, .24 * s, fill=c)
    circle(p, cx + .16 * s, cy - .02 * s, .2 * s, fill=c)


ICONS = {"user": _i_user, "attacker": _i_attacker, "browser": _i_browser, "mobile": _i_mobile, "service": _i_service,
         "api-gateway": _i_gateway, "load-balancer": _i_lb, "database": _i_db, "cache": _i_cache, "queue": _i_queue,
         "idp": _i_idp, "vault": _i_vault, "firewall": _i_firewall, "llm": _i_llm, "agent": _i_agent, "cdn": _i_cdn,
         "worker": _i_worker, "storage": _i_storage, "external": _i_external}


# ------------------------------------------------------------------ cards
def card_images(node, w, h):
    """(rgb, mask) of one component card at 2x with 6px of margin; also used to fade cards in."""
    m = 6
    p = Painter(w + 2 * m, h + 2 * m, 2, bg=BG)
    x0, y0, x1, y1 = m, m, m + w, m + h
    acc = ACCENT[node["kind"]]
    bad = node["kind"] == "attacker"
    p.rrect((x0, y0, x1, y1), r=20, fill=CARD, outline=mix(BORDER, acc, .5 if bad else .35), width=2)
    ICONS[node["kind"]](p, (x0 + x1) / 2, y0 + 47, 52, acc, CARD)
    lines = [node["label"]]
    size = 24
    if text_width(lines[0], "bold", size) > w - 28:
        lines = wrap(node["label"], "bold", 21, w - 28)[:2]
        size = 21
    if len(lines) == 1:
        text, size = fit(lines[0], "bold", size, w - 28, 17)
        p.text(((x0 + x1) / 2, y0 + 91), text, "bold", size, CREAM, anchor="mm")
    else:
        for k, ln in enumerate(lines):
            text, sz = fit(ln, "bold", 21, w - 28, 17)
            p.text(((x0 + x1) / 2, y0 + 80 + k * 22), text, "bold", sz, CREAM, anchor="mm")
    p.rrect((x0 + 12, y1 - 38, x1 - 12, y1 - 10), r=8, fill=STRIP)
    if node["note"]:
        text, sz = fit(node["note"], "sans", 18, w - 44, 15)
        p.text(((x0 + x1) / 2, y1 - 24), text, "sans", sz, MUTED, anchor="mm")
    rgb = p.img
    mask = Image.new("L", rgb.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([x0 * 2 - 2, y0 * 2 - 2, x1 * 2 + 2, y1 * 2 + 2], radius=40, fill=255)
    return rgb, mask


def draw_arrowhead(p, pts, color, size=11):
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    n = math.hypot(x1 - x0, y1 - y0) or 1
    ux, uy = (x1 - x0) / n, (y1 - y0) / n
    bx, by = x1 - ux * size, y1 - uy * size
    px, py = -uy, ux
    p.polygon([(x1, y1), (bx + px * size * .55, by + py * size * .55), (bx - px * size * .55, by - py * size * .55)],
              color)


def path_len(path):
    return sum(math.dist(a, b) for a, b in zip(path, path[1:]))


def point_on(path, f):
    total = path_len(path)
    d = max(0.0, min(1.0, f)) * total
    for a, b in zip(path, path[1:]):
        seg = math.dist(a, b)
        if d <= seg or (a, b) == (path[-2], path[-1]):
            t = d / seg if seg else 1.0
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        d -= seg
    return path[-1]


def draw_packet(p, x, y, label, kind, alpha=1.0, scale=1.0):
    color = KIND_COLOR[kind]
    col = mix(BG, color, alpha)
    size = 18
    text, size = fit(label, "bold", size, 190, 15)
    tw = text_width(text, "bold", size)
    glyph = 26 if kind in ("token", "attack", "error") else 0
    w, h = (tw + 26 + glyph) * scale, 34 * scale
    p.rrect((x - w / 2, y - h / 2, x + w / 2, y + h / 2), r=h / 2, fill=col, outline=mix(BG, "#ffffff", .5 * alpha),
            width=1.5)
    tx = x - w / 2 + 14 * scale + glyph * scale
    if kind == "token":      # a key
        gx = x - w / 2 + 22 * scale
        circle(p, gx - 3 * scale, y, 5.5 * scale, outline=INK, width=2.4)
        stroke(p, [(gx + 2 * scale, y), (gx + 11 * scale, y)], INK, 2.4)
        stroke(p, [(gx + 8 * scale, y), (gx + 8 * scale, y + 4.5 * scale)], INK, 2.4)
    elif kind in ("attack", "error"):
        gx = x - w / 2 + 22 * scale
        stroke(p, [(gx - 5 * scale, y - 5 * scale), (gx + 5 * scale, y + 5 * scale)], INK, 2.8)
        stroke(p, [(gx + 5 * scale, y - 5 * scale), (gx - 5 * scale, y + 5 * scale)], INK, 2.8)
    p.text((tx, y), text, "bold", size * scale, INK, anchor="lm")


def draw_badge(p, rect, status, alpha=1.0):
    color = mix(BG, STATUS_COLOR[status], alpha)
    cx, cy, r = rect[2] - 6, rect[1] + 6, 19
    circle(p, cx, cy, r + 3, fill=BG)
    circle(p, cx, cy, r, fill=color)
    if status == "ok":
        stroke(p, [(cx - 8, cy + 1), (cx - 2, cy + 7), (cx + 9, cy - 6)], INK, 4)
    elif status == "deny":
        stroke(p, [(cx - 7, cy - 7), (cx + 7, cy + 7)], INK, 4)
        stroke(p, [(cx + 7, cy - 7), (cx - 7, cy + 7)], INK, 4)
    elif status == "warn":
        p.text((cx, cy + 1), "!", "bold", 26, INK, anchor="mm")
    else:
        for dx in (-8, 0, 8):
            circle(p, cx + dx, cy, 2.8, fill=INK)


def glow(p, rect, color, g):
    if g <= .02:
        return
    for k, grow in enumerate((4, 8, 13)):
        c = mix(BG, color, g * (.75 - k * .22))
        p.rrect((rect[0] - grow, rect[1] - grow, rect[2] + grow, rect[3] + grow), r=20 + grow, outline=c, width=3)


# ------------------------------------------------------------------ timeline
@dataclass
class Seg:
    phase: str
    t0: float
    t1: float
    scene: int = 0
    step: int = -1          # index inside the scene
    g: int = -1             # index in the whole animation
    st: dict = None
    state: dict = field(default_factory=dict)
    status: dict = field(default_factory=dict)
    log: list = field(default_factory=list)
    caption: str = ""
    path: list = None
    changed: list = field(default_factory=list)


def build_timeline(spec, lay):
    steps_total = len(_flat(spec))
    segs, t = [], 0.0
    intro = min(3.0, .7 + .26 * len(spec["systems"]) + .5)
    segs.append(Seg("intro", t, t + intro, caption=spec["intro"]))
    t += intro
    # timing: scaled so the whole animation lands in 18-42 seconds
    base = dict(lead=.35, arrive=.55, hold=1.0, process=1.1)
    fixed = intro + 3.6 + (1.2 * len(spec["scenes"]) if len(spec["scenes"]) > 1 else 0)
    per = base["lead"] + base["arrive"] + base["hold"] + 1.25
    k = max(.62, min(1.25, (min(42.0, max(18.0, fixed + per * steps_total)) - fixed) / (per * steps_total)))
    g = 0
    log = []
    for si, sc in enumerate(spec["scenes"]):
        states, statuses = {}, {}
        if len(spec["scenes"]) > 1:
            segs.append(Seg("scene", t, t + 1.2, scene=si, caption=sc["title"]))
            t += 1.2
        for ni, st in enumerate(sc["steps"]):
            entry = {"g": g, "from": st["from"], "to": st["to"], "kind": st["kind"], "payload": st["payload"] or st["label"]}
            selfstep = st["from"] == st["to"]
            pre = dict(state=dict(states), status=dict(statuses))
            states.update(st["state"])
            statuses.update({n: v for n, v in st["status"].items()})
            statuses = {n: v for n, v in statuses.items() if v != "clear"}
            post = dict(state=dict(states), status=dict(statuses))
            path = None if selfstep else link_path(lay, st["from"], st["to"], _lane(spec, st["from"], st["to"]))
            travel = 1.0 if selfstep else (1.0 + min(.6, path_len(path) / 900)) * k
            mid = base["process"] * k if selfstep else travel
            common = dict(scene=si, step=ni, g=g, st=st, caption=st["caption"], path=path,
                          changed=list(st["state"]) + list(st["status"]))
            plan = [("lead", base["lead"] * k, pre, log), ("process" if selfstep else "travel", mid, pre, log + [entry]),
                    ("arrive", base["arrive"] * k, post, log + [entry]), ("hold", base["hold"] * k, post, log + [entry])]
            for phase, dur, snap, lg in plan:
                segs.append(Seg(phase, t, t + dur, state=snap["state"], status=snap["status"], log=list(lg), **common))
                t += dur
            log = log + [entry]
            g += 1
        log = [] if si + 1 < len(spec["scenes"]) else log
        last = (states, statuses)
    segs.append(Seg("outro", t, t + 3.6, scene=len(spec["scenes"]) - 1, g=g, state=last[0], status=last[1],
                    log=list(log), caption=spec["takeaway"]))
    return segs


def _lane(spec, a, b):
    """Sideways shift of the connection a -> b: the two directions of a pair run side by side."""
    both = any((x["from"], x["to"]) == (b, a) for x in _flat(spec))
    if not both:
        return 0.0
    return -12.0 if a < b else 12.0


# ------------------------------------------------------------------ the renderer
class Renderer:
    def __init__(self, raw, handle=""):
        self.spec = clean(raw)
        bad = validate_spec(self.spec)
        if bad:
            raise SysflowError("; ".join(bad[:4]))
        self.handle = handle
        self.nodes = {s["id"]: s for s in self.spec["systems"]}
        self.lay = choose_layout(self.spec)
        self.rects = {i: _rect(self.lay, c) for i, c in self.lay.centers.items()}
        self.cards = {i: card_images(n, int(self.lay.w), int(self.lay.h)) for i, n in self.nodes.items()}
        self.segs = build_timeline(self.spec, self.lay)
        self.total = self.segs[-1].t1
        self.links = self._links()
        self.base = self._base()
        self.static2x = self._static()
        self._panel_cache = {}

    # ----- cached layers
    def _links(self):
        out = {}
        for st in _flat(self.spec):
            if st["from"] != st["to"]:
                key = (st["from"], st["to"])
                out[key] = link_path(self.lay, st["from"], st["to"], _lane(self.spec, *key))
        return out

    def _base(self):
        p = Painter(W, H, 2)
        pill(p, (60, 52), self.spec["kicker"], size=20, height=44)
        title = self.spec["title"]
        size = next((sz for sz in (54, 50, 46) if len(wrap(title, "bold", sz, 960)) == 1), 50)
        y = 112
        for ln in wrap(title, "bold", size, 960)[:2]:
            p.text((60, y), ln, "bold", size, CREAM)
            y += size + 8
        sub, sz = fit(self.spec["subtitle"], "sans", 26, 960, 20)
        p.text((60, y + 6), sub, "sans", sz, MUTED)
        footer(p, "Simplified illustration, not a real system", self.handle, y_rule=1257)
        return p.result()

    def _bg2x(self):
        p = Painter(W, DH, 2)
        return p

    def _draw_links(self, p, fade=None):
        for (a, b), path in self.links.items():
            f = 1.0 if fade is None else fade.get((a, b), 0.0)
            if f <= 0:
                continue
            col = mix(BG, EDGE_DIM, f)
            stroke(p, path, col, 4)
            draw_arrowhead(p, path, col)

    def _static(self):
        p = self._bg2x()
        self._draw_links(p)
        for i, (rgb, mask) in self.cards.items():
            c = self.lay.centers[i]
            p.img.paste(rgb, (int((c[0] - self.lay.w / 2 - 6) * 2), int((c[1] - self.lay.h / 2 - 6) * 2)), mask)
        return p.img

    def _painter(self):
        p = Painter(W, DH, 2)
        p.img = self.static2x.copy()
        p.d = ImageDraw.Draw(p.img)
        return p

    # ----- the three parts of a frame
    def frame(self, t):
        seg = next((s for s in self.segs if t < s.t1), self.segs[-1])
        lt = (t - seg.t0) / max(1e-6, seg.t1 - seg.t0)
        diag = self._diagram(seg, max(0.0, min(1.0, lt)))
        img = self.base.copy()
        img.paste(diag, (0, DY))
        img.paste(self._panels(seg), (0, CAP_Y))
        return img

    def key(self, t):
        """Frames with the same key are identical (a hold), so they are rendered once."""
        seg = next((s for s in self.segs if t < s.t1), self.segs[-1])
        return (id(seg),) if seg.phase in ("hold", "scene", "outro") else None

    def _diagram(self, seg, u):
        if seg.phase == "intro":
            return self._intro(u)
        p = self._painter()
        self._ribbon(p, seg)
        if seg.phase == "outro":
            for node, val in seg.status.items():
                draw_badge(p, self.rects[node], val)
            self._states(p, seg)
            return p.img.reduce(2)
        st = seg.st
        color = KIND_COLOR[st["kind"]] if st else TEAL
        if seg.phase == "scene":
            self._states(p, seg)
            return p.img.reduce(2)
        a, b = st["from"], st["to"]
        if seg.phase in ("lead", "travel", "arrive", "hold", "process") and seg.path:
            on = {"lead": .0, "travel": 1.0, "arrive": .6, "hold": .0}.get(seg.phase, 0)
            if on:
                stroke(p, seg.path, mix(EDGE_DIM, color, .55 * on), 5)
                draw_arrowhead(p, seg.path, mix(EDGE_DIM, color, .55 * on), 12)
        self._states(p, seg)
        for node, val in seg.status.items():
            draw_badge(p, self.rects[node], val)
        if seg.phase == "lead":
            glow(p, self.rects[a], color, ease(u))
        elif seg.phase == "travel":
            glow(p, self.rects[a], color, .55 * (1 - u) + .15)
            self._packet(p, seg, ease(u))
        elif seg.phase == "process":
            glow(p, self.rects[a], color, .45 + .35 * math.sin(u * math.pi * 4) ** 2)
            self._bubble(p, a, st["label"], color)
            self._spinner(p, a, u, color)
        elif seg.phase == "arrive":
            target = b
            glow(p, self.rects[target], color, ease(min(1.0, u * 1.6)))
            if not seg.path:
                self._bubble(p, a, st["label"], color)
            else:
                self._ripple(p, seg, u, color)
            for node in seg.changed:
                self._flash(p, node, 1 - u, color)
        elif seg.phase == "hold":
            glow(p, self.rects[b], color, max(.0, .5 * (1 - u)))
            if not seg.path:
                self._bubble(p, a, st["label"], color)
        return p.img.reduce(2)

    def _intro(self, u):
        p = Painter(W, DH, 2)
        n = len(self.nodes)
        total = self.segs[0].t1 - self.segs[0].t0
        t = u * total
        prog = {}
        for k, i in enumerate(self.nodes):
            prog[i] = ease((t - .15 - k * .26) / .5)
        fade = {(a, b): ease(min(prog[a], prog[b]) * 1.3 - .15) for (a, b) in self.links}
        self._draw_links(p, fade)
        for i, (rgb, mask) in self.cards.items():
            f = prog[i]
            if f <= 0:
                continue
            sc = .86 + .14 * f
            w, h = rgb.size
            r2 = rgb.resize((max(1, int(w * sc)), max(1, int(h * sc))), Image.BILINEAR)
            m2 = mask.resize(r2.size, Image.BILINEAR).point(lambda v, f=f: int(v * f))
            c = self.lay.centers[i]
            p.img.paste(r2, (int(c[0] * 2 - r2.size[0] / 2), int(c[1] * 2 - r2.size[1] / 2)), m2)
        return p.img.reduce(2)

    # ----- dynamic pieces
    def _ribbon(self, p, seg):
        scenes = self.spec["scenes"]
        if len(scenes) < 2 or seg.phase == "intro":
            return
        label = f"SCENE {seg.scene + 1} OF {len(scenes)}"
        right = pill(p, (60, 6), label, fill=GOLD, size=18, height=38)
        title, sz = fit(scenes[seg.scene]["title"], "semi", 28, 960 - (right - 60) - 20, 20)
        p.text((right + 18, 25), title, "semi", sz, CREAM, anchor="lm")

    def _states(self, p, seg):
        for node, text in seg.state.items():
            x0, y0, x1, y1 = self.rects[node]
            hot = node in seg.changed and seg.phase in ("arrive",)
            p.rrect((x0 + 12, y1 - 38, x1 - 12, y1 - 10), r=8, fill=STRIP, outline=ACCENT[self.nodes[node]["kind"]], width=1.5)
            t, sz = fit(text, "mono", 18, self.lay.w - 48, 14)
            p.text(((x0 + x1) / 2, y1 - 24), t, "mono", sz, CREAM, anchor="mm")

    def _flash(self, p, node, f, color):
        if node not in self.rects or f <= 0:
            return
        x0, y0, x1, y1 = self.rects[node]
        p.rrect((x0 + 12, y1 - 38, x1 - 12, y1 - 10), r=8, outline=mix(STRIP, color, f), width=3)

    def _packet(self, p, seg, u):
        path = seg.path
        st = seg.st
        color = KIND_COLOR[st["kind"]]
        for k in range(1, 5):
            f = u - k * .035
            if f > 0:
                x, y = point_on(path, f)
                circle(p, x, y, 9 - k * 1.6, fill=mix(BG, color, .5 - k * .1))
        x, y = point_on(path, u)
        draw_packet(p, x, y, st["label"], st["kind"])

    def _ripple(self, p, seg, u, color):
        x, y = seg.path[-1]
        r = 8 + 40 * ease(u)
        circle(p, x, y, r, outline=mix(BG, color, 1 - u), width=3)

    def _bubble(self, p, node, label, color):
        x0, y0, x1, y1 = self.rects[node]
        text, sz = fit(label, "bold", 19, 230, 15)
        w = text_width(text, "bold", sz) + 32
        cx = (x0 + x1) / 2
        by = y0 - 26 if y0 > 90 else y1 + 26
        p.rrect((cx - w / 2, by - 18, cx + w / 2, by + 18), r=18, fill=mix(BG, color, 1), outline=mix(BG, "#ffffff", .5), width=1.5)
        p.text((cx, by), text, "bold", sz, INK, anchor="mm")

    def _spinner(self, p, node, u, color):
        x0, y0, x1, y1 = self.rects[node]
        cx, cy = (x0 + x1) / 2, y0 + 47
        for k in range(3):
            a = u * 2 * math.pi * 2 + k * 2 * math.pi / 3
            circle(p, cx + 40 * math.cos(a), cy + 40 * math.sin(a), 4.5, fill=mix(CARD, color, 1 - k * .25))

    # ----- caption and wire log (change only between steps)
    def _panels(self, seg):
        key = (seg.phase in ("intro", "scene", "outro"), seg.phase if seg.phase in ("intro", "scene", "outro") else "",
               seg.scene, seg.g, tuple(e["g"] for e in seg.log), seg.phase == "lead")
        if key in self._panel_cache:
            return self._panel_cache[key]
        p = Painter(W, 1250 - CAP_Y, 2)
        total = len(_flat(self.spec))
        # caption: the tag on the first row, the sentence under it (one or two lines)
        p.rrect((60, 0, 1020, CAP_H), r=22, fill=CARD_HI, outline=TEAL if seg.phase != "outro" else GOLD, width=2)
        if seg.phase == "outro":
            tag, color = "TAKEAWAY", GOLD
        elif seg.phase == "intro":
            tag, color = "THE SYSTEM", TEAL
        elif seg.phase == "scene":
            tag, color = f"SCENE {seg.scene + 1}", GOLD
        else:
            tag, color = f"STEP {seg.g + 1} OF {total}", TEAL
        pill(p, (84, 14), tag, fill=color, size=17, height=32)
        lines = wrap(seg.caption, "semi", 26, 896)[:2]
        ys = (88,) if len(lines) == 1 else (80, 108)
        for ln, y in zip(lines, ys):
            p.text((84, y), ln, "semi", 26, CREAM, anchor="lm")
        # wire log
        y0 = LOG_Y - CAP_Y
        p.rrect((60, y0, 1020, y0 + LOG_H), r=22, fill=CODE_BG, outline="#1f3f66", width=2)
        p.text((84, y0 + 24), "ON THE WIRE", "bold", 17, MUTED, anchor="lm", tracking=2.2)
        shown = seg.log[-3:]
        if not shown:
            p.text((84, y0 + 70), "waiting for the first message", "mono", 19, mix(CODE_BG, MUTED, .6), anchor="lm")
        for k, e in enumerate(shown):
            y = y0 + 44 + k * 31
            cur = e["g"] == seg.g and seg.phase not in ("outro", "intro", "scene") and seg.phase != "lead"
            if cur:
                p.rrect((70, y - 3, 1010, y + 27), r=8, fill=HL_LINE)
            col = KIND_COLOR[e["kind"]]
            circle(p, 92, y + 12, 6, fill=col)
            who = f"{self.nodes[e['from']]['label']} \u2192 {self.nodes[e['to']]['label']}" if e["from"] != e["to"] \
                else f"{self.nodes[e['from']]['label']} (itself)"
            who, wsz = fit(who, "semi", 19, 330, 15)
            p.text((112, y + 12), who, "semi", wsz, CREAM if cur else MUTED, anchor="lm")
            payload, psz = fit(e["payload"], "mono", 19, 1000 - 470, 14)
            p.text((470, y + 12), payload, "mono", psz, col if cur else mix(CODE_BG, col, .7), anchor="lm")
        img = p.result()
        self._panel_cache[key] = img
        return img


# ------------------------------------------------------------------ output
def render_sysflow(raw, out_path, handle="", still_path=None, fps=FPS):
    """Encode the animation to an MP4 (and the final frame to a PNG). Returns {path, seconds, frames, still}."""
    if not shutil.which("ffmpeg"):
        raise SysflowError("ffmpeg is not installed (macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt install ffmpeg)")
    r = Renderer(raw, handle)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    n = int(round(r.total * fps))
    cache = {}
    try:
        for i in range(n):
            t = min(r.total - 1e-4, i / fps)
            key = r.key(t)
            if key is not None and key in cache:
                data = cache[key]
            else:
                data = r.frame(t).tobytes()
                if key is not None:
                    cache[key] = data
            proc.stdin.write(data)
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        proc.stderr.close()
        if proc.wait() != 0:
            raise SysflowError(f"ffmpeg failed: {err[-400:]}")
    except BrokenPipeError:
        raise SysflowError(f"ffmpeg stopped early: {proc.stderr.read().decode(errors='replace')[-400:]}")
    still = None
    if still_path:
        still = Path(still_path)
        r.frame(r.total - 0.05).save(still)
    return {"path": str(out), "seconds": n / fps, "frames": n, "still": str(still) if still else None}


def preview(raw, times, out_dir, handle=""):
    """PNG stills at the given times (seconds), for looking at a design without encoding a video."""
    r = Renderer(raw, handle)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in times:
        path = out / f"frame-{t:05.1f}.png"
        r.frame(min(t, r.total - 0.05)).save(path)
        paths.append(str(path))
    return r.total, paths


if __name__ == "__main__":   # python -m postcrew.render.sysflow spec.json out.mp4   |   ... spec.json --stills dir t1 t2 ...
    import sys
    spec = json.load(open(sys.argv[1]))
    if len(sys.argv) > 3 and sys.argv[2] == "--stills":
        total, files = preview(spec, [float(x) for x in sys.argv[4:]], sys.argv[3])
        print(total, *files, sep="\n")
    else:
        print(render_sysflow(spec, sys.argv[2], still_path=str(Path(sys.argv[2]).with_suffix(".png"))))
