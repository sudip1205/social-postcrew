"""Explainer video: a slow, clean animated explanation, drawn to the voice.

The look follows the best system-design channels: a dark screen, one picture that keeps growing while the narrator explains
(each box pops in when its name is said, each arrow draws itself and a dot travels along it), the thing being explained
glowing while the rest dims, a handwritten title per chapter, and short highlighted caption chunks timed to the words.

Every scene of a diagram that shares boxes with the scene before it is drawn on the same canvas: the earlier boxes and arrows
are already there and only the new ones animate in. Timings come from the voice (render/timeline.py, measured on the real audio),
so the picture is always in step with the words. Pillow draws everything; ffmpeg joins the frames. Nothing else to install.
"""
import math
import random
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import timeline
from .blackboard import _plen, _routes, _upto, _wobble
from .scenes import FORMATS, parse_edge, parse_pointer, place_diagram, split_node
from .syntax import tokenize
from .theme import FONT_DIR
from .video import ENC, FPS, VideoError, _run

DRAW_FPS = 24
SS = 2   # sprites are drawn at twice the size and scaled down: smooth edges
BG, BG2 = (17, 18, 24), (9, 10, 13)
CARD, CARD_HI, BORDER = (26, 28, 36), (34, 37, 48), (52, 56, 70)
TEXT, MUTED = (243, 244, 246), (155, 161, 173)
PURPLE, VIOLET, AMBER, TEAL = (124, 58, 237), (167, 139, 250), (245, 184, 61), (45, 212, 191)
PINK, GREEN, BLUE, RED = (244, 114, 182), (74, 222, 128), (96, 165, 250), (248, 113, 113)
HOLD_S = 3.2     # how long the newest thing stays highlighted
MAX_GROUP_NODES, MAX_GROUP_EDGES = 9, 14

_FONTS = {"hand": "CaveatBrush-Regular.ttf", "bold": "Inter-Bold.ttf", "semi": "Inter-SemiBold.ttf", "reg": "Inter-Regular.ttf",
          "mono": "JetBrainsMono-Regular.ttf", "monob": "JetBrainsMono-Bold.ttf"}
_SWAP = {"→": "->", "←": "<-", "≤": "<=", "≥": ">=", "≈": "~", "“": '"', "”": '"', "’": "'", "—": "-"}


def _clean(s):
    return "".join(_SWAP.get(c, c) for c in str(s or "")).strip()


@lru_cache(maxsize=None)
def font(kind, size):
    return ImageFont.truetype(str(FONT_DIR / _FONTS[kind]), max(6, int(round(size))))


def wrap(text, kind, size, max_w):
    lines, f = [], font(kind, size)
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}".strip()
            if not cur or f.getlength(trial) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def fit(text, kind, max_w, max_h, start, lo, lh=1.2):
    size = start
    while True:
        lines = wrap(text, kind, size, max_w)
        if (max(font(kind, size).getlength(ln) for ln in lines) <= max_w and len(lines) * size * lh <= max_h) or size <= lo:
            return lines, size
        size -= 2


def _down(im):
    return im.resize((max(1, im.width // SS), max(1, im.height // SS)), Image.LANCZOS)


def tx(text, kind, size, color, stroke=0):
    """A line of text as a sprite."""
    f, sw = font(kind, size * SS), stroke * SS
    l, t, r, b = f.getbbox(text or " ", stroke_width=sw)
    im = Image.new("RGBA", (r + 6 * SS, b + 6 * SS), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((0, 0), text, font=f, fill=(*color, 255), stroke_width=sw, stroke_fill=(*color, 255))
    return _down(im)


def _fade(sp, a):
    if a >= 0.999:
        return sp
    out = sp.copy()
    out.putalpha(sp.getchannel("A").point([int(i * max(0.0, a)) for i in range(256)]))
    return out


def _put(canvas, sp, x, y):
    x, y = int(round(x)), int(round(y))
    W, H = canvas.size
    if x >= W or y >= H or x + sp.width <= 0 or y + sp.height <= 0:
        return
    sx, sy = max(0, -x), max(0, -y)
    ex, ey = min(sp.width, W - x), min(sp.height, H - y)
    canvas.alpha_composite(sp.crop((sx, sy, ex, ey)), (x + sx, y + sy))


def _back(f):
    c1 = 1.4
    c3 = c1 + 1
    return 1 + c3 * (f - 1) ** 3 + c1 * (f - 1) ** 2


# ---------- icons (drawn on a 64 x 64 grid) ----------
def icon2x(kind, px, color):
    S = px * SS
    k = S / 64
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c, soft = (*color, 255), (*color, 70)

    def rr(x0, y0, x1, y1, r=6, fill=None, w=4):
        d.rounded_rectangle([x0 * k, y0 * k, x1 * k, y1 * k], r * k, fill=fill, outline=c, width=int(w * k))

    def ln(pts, w=4):
        d.line([(x * k, y * k) for x, y in pts], fill=c, width=int(w * k), joint="curve")

    def el(x0, y0, x1, y1, fill=None, w=4):
        d.ellipse([x0 * k, y0 * k, x1 * k, y1 * k], fill=fill, outline=c, width=int(w * k))

    if kind == "client":
        rr(8, 12, 56, 42, 5, soft)
        ln([(3, 51), (61, 51)])
        ln([(26, 42), (26, 51)], 3)
        ln([(38, 42), (38, 51)], 3)
    elif kind == "phone":
        rr(19, 5, 45, 59, 7, soft)
        el(29, 49, 35, 55, c, 2)
    elif kind == "server":
        for y in (6, 24, 42):
            rr(8, y, 56, y + 15, 4, soft)
            el(15, y + 4, 22, y + 11, c, 1)
            ln([(30, y + 7.5), (48, y + 7.5)], 2.5)
    elif kind == "database":
        el(12, 6, 52, 22, soft)
        ln([(12, 14), (12, 48)])
        ln([(52, 14), (52, 48)])
        d.arc([12 * k, 18 * k, 52 * k, 34 * k], 0, 180, fill=c, width=int(4 * k))
        d.arc([12 * k, 32 * k, 52 * k, 48 * k], 0, 180, fill=c, width=int(4 * k))
        d.arc([12 * k, 42 * k, 52 * k, 58 * k], 0, 180, fill=c, width=int(4 * k))
    elif kind == "cache":
        d.polygon([(37 * k, 4 * k), (14 * k, 36 * k), (29 * k, 36 * k), (25 * k, 60 * k), (50 * k, 25 * k), (34 * k, 25 * k)], fill=c)
    elif kind == "queue":
        rr(3, 20, 21, 44, 4, soft)
        rr(23, 20, 41, 44, 4, soft)
        rr(43, 20, 61, 44, 4, c)
        ln([(8, 55), (56, 55)], 3)
        d.polygon([(56 * k, 50 * k), (62 * k, 55 * k), (56 * k, 60 * k)], fill=c)
    elif kind == "gateway":
        d.polygon([(32 * k, 4 * k), (60 * k, 32 * k), (32 * k, 60 * k), (4 * k, 32 * k)], fill=soft, outline=c, width=int(4 * k))
        ln([(18, 32), (44, 32)])
        d.polygon([(42 * k, 25 * k), (52 * k, 32 * k), (42 * k, 39 * k)], fill=c)
    elif kind == "user":
        el(21, 6, 43, 28, soft)
        d.pieslice([8 * k, 34 * k, 56 * k, 82 * k], 180, 360, fill=soft, outline=c, width=int(4 * k))
    elif kind == "cloud":
        for box in ((8, 28, 32, 52), (20, 14, 46, 42), (36, 24, 58, 52), (12, 36, 54, 52)):
            d.ellipse([b * k for b in box], fill=c)
    elif kind == "lock":
        rr(12, 28, 52, 58, 6, soft)
        d.arc([19 * k, 6 * k, 45 * k, 42 * k], 180, 360, fill=c, width=int(4.5 * k))
        el(28, 38, 36, 46, c, 1)
    elif kind == "key":
        el(5, 20, 31, 46, soft)
        ln([(31, 33), (60, 33)])
        ln([(52, 33), (52, 44)])
        ln([(43, 33), (43, 41)])
    elif kind == "file":
        d.polygon([(14 * k, 4 * k), (40 * k, 4 * k), (52 * k, 16 * k), (52 * k, 60 * k), (14 * k, 60 * k)], fill=soft, outline=c, width=int(4 * k))
        ln([(40, 4), (40, 16), (52, 16)], 3)
        ln([(22, 32), (44, 32)], 3)
        ln([(22, 42), (44, 42)], 3)
    elif kind == "terminal":
        rr(4, 9, 60, 55, 7, soft)
        ln([(15, 23), (26, 32), (15, 41)])
        ln([(31, 43), (46, 43)])
    elif kind == "globe":
        el(6, 6, 58, 58, soft)
        el(22, 6, 42, 58, None, 3)
        ln([(6, 32), (58, 32)], 3)
    elif kind == "service":
        rr(14, 14, 50, 50, 6, soft)
        for p in (22, 32, 42):
            ln([(p, 5), (p, 14)], 3)
            ln([(p, 50), (p, 59)], 3)
            ln([(5, p), (14, p)], 3)
            ln([(50, p), (59, p)], 3)
        rr(24, 24, 40, 40, 3, c, 1)
    else:
        rr(8, 8, 56, 56, 12, soft)
        el(25, 25, 39, 39, c, 1)
    return im


ICON_WORDS = [("client", "client browser laptop desktop"), ("phone", "phone mobile app ios android"), ("user", "user customer person actor admin"),
              ("database", "database db sql postgres mysql mongo dynamo storage store disk replica shard"), ("cache", "cache redis memcache"),
              ("queue", "queue kafka broker rabbit stream topic sqs pubsub"), ("gateway", "gateway proxy balancer router apigee kong ingress mesh"),
              ("cloud", "cloud cdn aws gcp azure"), ("globe", "internet web dns network website"), ("lock", "auth lock secure tls ssl encrypt"),
              ("key", "key token secret hash jwt password"), ("file", "file log document config image"), ("terminal", "terminal cli shell command"),
              ("server", "server node host machine instance"), ("service", "service worker api backend microservice container pod job")]
ICON_COLOR = {"client": BLUE, "phone": BLUE, "user": BLUE, "database": AMBER, "cache": PINK, "queue": VIOLET, "gateway": VIOLET,
              "cloud": BLUE, "globe": BLUE, "lock": PINK, "key": PINK, "file": GREEN, "terminal": GREEN, "server": TEAL,
              "service": TEAL, "generic": VIOLET}


def guess_icon(label, hint=""):
    from .scenes import ICONS
    if hint in ICONS:
        return hint
    low = label.lower()
    for icon, words in ICON_WORDS:
        if any(w in low for w in words.split()):
            return icon
    return "generic"


# ---------- sprites ----------
def card2x(w, h, fill=CARD, border=BORDER, r=22, pad=22, bw=2):
    """A rounded card with a soft shadow, at twice the size (so things can be put on it before scaling down)."""
    W, H = (w + 2 * pad) * SS, (h + 2 * pad) * SS
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad * SS, (pad + 7) * SS, (pad + w) * SS, (pad + h + 7) * SS], r * SS, fill=(0, 0, 0, 170))
    im = sh.filter(ImageFilter.GaussianBlur(11 * SS))
    ImageDraw.Draw(im).rounded_rectangle([pad * SS, pad * SS, (pad + w) * SS, (pad + h) * SS], r * SS, fill=(*fill, 255),
                                         outline=(*border, 255), width=bw * SS)
    return im


def node_sprite(label, icon, w, h):
    """A box with an icon and the name. Wide boxes: icon on the left; narrow ones: icon above. Returns (sprite, padding)."""
    pad = 22
    im = card2x(w, h)
    col = ICON_COLOR.get(icon, VIOLET)
    d = ImageDraw.Draw(im)
    if w < 250 and h > 100:   # stacked: the name gets the whole width
        ip = int(min(h * 0.42, w * 0.34))
        im.alpha_composite(icon2x(icon, ip, col), ((pad + (w - ip) // 2) * SS, (pad + 12) * SS))
        lines, size = fit(label, "bold", w - 20, h - ip - 28, 30, 14, 1.12)
        f = font("bold", size * SS)
        y = (pad + 12 + ip + 8) * SS
        for ln in lines:
            d.text(((pad + w / 2) * SS, y), ln, font=f, fill=(*TEXT, 255), anchor="ma")
            y += size * 1.12 * SS
        return _down(im), pad
    ip = int(h - 30)
    im.alpha_composite(icon2x(icon, ip, col), ((pad + 16) * SS, (pad + (h - ip) // 2) * SS))
    avail = w - ip - 16 - 16 - 14
    lines, size = fit(label, "bold", avail, h - 22, min(42, h * 0.34), 15, 1.15)
    f = font("bold", size * SS)
    y = pad * SS + (h * SS - len(lines) * size * 1.15 * SS) / 2
    for ln in lines:
        d.text(((pad + 16 + ip + 14) * SS, y), ln, font=f, fill=(*TEXT, 255))
        y += size * 1.15 * SS
    return _down(im), pad


def iso_node_sprite(label, icon, w, h):
    """The same box as node_sprite, drawn as a solid block: a lit top, a darker side and a front face with the icon and name."""
    d = int(max(10, min(22, h * 0.13)))
    front, pad = node_sprite(label, icon, w - d, h - d)
    col = ICON_COLOR.get(icon, VIOLET)
    W, H = (w + 2 * pad) * SS, (h + 2 * pad) * SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).polygon([((pad + 6) * SS, (pad + h + 6) * SS), ((pad + w - d + 6) * SS, (pad + h + 8) * SS),
                                ((pad + w + 10) * SS, (pad + h - d + 12) * SS), ((pad + d + 4) * SS, (pad + h + 14) * SS)], fill=(0, 0, 0, 150))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(9 * SS)))
    dr = ImageDraw.Draw(im)
    top = [(pad, pad + d), (pad + d, pad), (pad + w, pad), (pad + w - d, pad + d)]
    side = [(pad + w - d, pad + d), (pad + w, pad), (pad + w, pad + h - d), (pad + w - d, pad + h)]
    mix = lambda a, b, k: tuple(int(a[i] * (1 - k) + b[i] * k) for i in range(3))
    dr.polygon([(x * SS, y * SS) for x, y in top], fill=(*mix(CARD_HI, col, 0.42), 255), outline=(*col, 255))
    dr.polygon([(x * SS, y * SS) for x, y in side], fill=(*mix(BG2, col, 0.16), 255), outline=(*mix(BORDER, col, 0.5), 255))
    big = front.resize((front.width * SS, front.height * SS), Image.BILINEAR)
    im.alpha_composite(big, (0, d * SS))
    dr = ImageDraw.Draw(im)
    dr.line([((pad) * SS, (pad + d) * SS), ((pad + w - d) * SS, (pad + d) * SS)], fill=(*col, 255), width=3 * SS)
    return _down(im), pad


def pill_sprite(text, size, color=VIOLET, fill=(20, 21, 28)):
    f = font("semi", size * SS)
    wd = int(f.getlength(text)) + 28 * SS
    ht = int(size * 1.7 * SS)
    im = Image.new("RGBA", (wd, ht), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, wd - 1, ht - 1], ht // 2, fill=(*fill, 245), outline=(*color, 255), width=2 * SS)
    d.text((14 * SS, ht / 2), text, font=f, fill=(*color, 255), anchor="lm")
    return _down(im)


def heading_sprite(text, g):
    """The chapter title: handwritten, amber, with a hand-drawn underline."""
    lines, size = fit(_clean(text), "hand", g["x1"] - g["x0"], g["head"] * 2.3, g["head"], 34, 1.05)
    f = font("hand", size * SS)
    wd = int(max(f.getlength(ln) for ln in lines)) + 12 * SS
    lh = int(size * 1.05 * SS)
    im = Image.new("RGBA", (wd, lh * len(lines) + 30 * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        d.text((4 * SS, i * lh), ln, font=f, fill=(*AMBER, 255))
    y = lh * len(lines) + 8 * SS
    rnd = random.Random(len(text))
    pts = _wobble([(4 * SS, y), (wd - 8 * SS, y + 3 * SS)], rnd, 2.2 * SS, step=10 * SS)
    d.line(pts, fill=(*AMBER, 255), width=4 * SS, joint="curve")
    return _down(im)


# ---------- layout ----------
def _geom(fmt):
    w, h = FORMATS[fmt]
    short = h > w
    u = w if short else h
    x0 = 96 if short else 150
    return {"w": w, "h": h, "short": short, "u": u, "x0": x0, "x1": w - x0, "top": 150 if short else 112,
            "cap_cy": h * (0.885 if short else 0.925), "bot": h * (0.775 if short else 0.80),
            "body": u * (0.040 if short else 0.052), "head": u * (0.082 if short else 0.088),
            "max_bw": 660 if short else 330, "max_bh": 150 if short else 190}   # how big a box may get (render/scenes.place_diagram)


class Item:
    """One thing on the screen: a sprite (a box, a label, a bullet, a code line, the title) or a link (an arrow)."""

    def __init__(self, kind="sprite", img=None, xy=(0, 0), cue=None, dur=0.8, what="", anim="pop", pre=False, gid="",
                 also=(), box=None, ring=False, focusable=True, head=False, pts=None, color=VIOLET, data=None):
        self.kind, self.img, self.xy, self.cue, self.dur, self.what, self.anim = kind, img, xy, cue, dur, what, anim
        self.pre, self.gid, self.also, self.box, self.ring, self.focusable, self.head = pre, gid, tuple(also), box, ring, focusable, head
        self.pts, self.color, self.data = pts, color, data   # data: the steps of a trace or a flow (drawn by time, see _draw_trace)
        self.starts = []


def _heading_item(g, text, items):
    text = _clean(text)
    if not text:
        return g["top"]
    sp = heading_sprite(text, g)
    items.append(Item(img=sp, xy=(g["x0"], g["top"]), dur=1.0, what="heading", anim="wipe", head=True, focusable=False))
    return g["top"] + sp.height + 26


def _is_diagram(sc):
    return sc.get("layout") == "diagram" and len([n for n in sc.get("nodes") or [] if split_node(n)[0]]) >= 2


def plan_groups(scenes):
    """Consecutive diagram scenes that share a box are drawn on one canvas. Per scene: the union of boxes and arrows (so every
    scene lays them out the same way), and what the scenes before it already drew."""
    out, i = [None] * len(scenes), 0
    while i < len(scenes):
        if not _is_diagram(scenes[i]):
            i += 1
            continue
        nodes, edges, seen = [], [], set()
        j = i
        while j < len(scenes) and _is_diagram(scenes[j]):
            sc = scenes[j]
            labels = {split_node(n)[0].lower() for n in sc["nodes"] if split_node(n)[0]}
            add_n = [n for n in sc["nodes"] if split_node(n)[0] and split_node(n)[0].lower() not in {split_node(x)[0].lower() for x in nodes}]
            add_e = [e for e in sc.get("edges") or [] if e not in edges]
            if j > i and (not (labels & {split_node(x)[0].lower() for x in nodes}) or len(nodes) + len(add_n) > MAX_GROUP_NODES
                          or len(edges) + len(add_e) > MAX_GROUP_EDGES):
                break
            nodes += add_n
            edges += add_e
            j += 1
        carry_n, carry_e = [], []
        for k in range(i, j):
            out[k] = {"nodes": list(nodes), "edges": list(edges), "carry_nodes": list(carry_n), "carry_edges": list(carry_e)}
            carry_n += [split_node(n)[0].lower() for n in scenes[k]["nodes"]]
            carry_e += list(scenes[k].get("edges") or [])
        i = j
    return out


def _spoken_later(words, after, *phrases):
    """Of these phrases, the one the narrator says last (after `after`), and when; (None, after) if none is said."""
    best, at = None, after
    for ph in phrases:
        t = timeline.cue_time(ph, words, after=after) if ph else None
        if t is not None and t >= at:
            best, at = ph, t
    return best, at


def _diagram(g, scene, items, group):
    y = _heading_item(g, scene.get("on_screen"), items)
    if not group:
        group = {"nodes": scene["nodes"], "edges": scene.get("edges") or [], "carry_nodes": [], "carry_edges": []}
    nodes = [n for n in group["nodes"] if split_node(n)[0]]
    labels = [split_node(n)[0][:18] for n in nodes]
    valid = [(e, parse_edge(e, nodes)) for e in group["edges"]]
    valid = [(e, p) for e, p in valid if p]
    tuples = [p for _e, p in valid]
    boxes, rows, vertical = place_diagram(g, tuples, len(nodes), y)
    routes = _routes(g, boxes, rows, vertical, tuples, y)
    by_edge = {e: (p, routes[k]) for k, (e, p) in enumerate(valid)}
    carry_n, carry_e = set(group["carry_nodes"]), set(group["carry_edges"])
    added = set()
    words = timeline.word_times(str(scene.get("narration", "")), 100.0)   # only the order of the words matters here
    said = [0.0]   # when the last thing drawn is spoken: the next one is looked for after it

    def node(i, pre):
        if i in added:
            return
        added.add(i)
        l, t, r, b = boxes[i]
        icon = guess_icon(labels[i], split_node(nodes[i])[1])
        sp, pad = iso_node_sprite(labels[i], icon, int(r - l), int(b - t))
        if not pre:   # a faint outline of the block is there before it is named: the screen is never empty
            items.append(Item(img=_fade(sp, 0.22), xy=(l - pad, t - pad), what="ghost", pre=True, focusable=False))
        items.append(Item(img=sp, xy=(l - pad, t - pad), cue=labels[i], dur=0.9, what="box", anim="pop", pre=pre,
                          gid=f"n:{i}", box=(l, t, r, b), ring=True))
        if not pre:
            said[0] = _spoken_later(words, said[0], labels[i])[1]

    def edge(e, pre):
        (i, j, label), (pts, pos, anchor, _col) = by_edge[e][0], by_edge[e][1]
        node(i, pre)
        node(j, pre)
        back = i > j
        color = AMBER if back else VIOLET
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        box = (int(min(xs)) - 26, int(min(ys)) - 26, int(max(xs)) + 26, int(max(ys)) + 26)
        gid = f"e:{e}"
        # the arrow is drawn when the narrator has said both what it is called and where it goes: the later of the two
        cue = _spoken_later(words, 0.0, label, labels[j])[0] or label or labels[j]
        if not pre:
            said[0] = _spoken_later(words, said[0], cue)[1]
        items.append(Item(kind="link", pts=pts, color=color, box=box, cue=cue, dur=0.9, what="arrow", pre=pre,
                          gid=gid, also=(f"n:{i}", f"n:{j}")))
        if label:
            sp = pill_sprite(_clean(label), max(15, int(g["body"] * 0.52)), color)
            x = {"l": pos[0], "m": pos[0] - sp.width / 2, "r": pos[0] - sp.width}[anchor[0]]
            yy = {"t": pos[1], "m": pos[1] - sp.height / 2, "b": pos[1] - sp.height}[anchor[1]]
            items.append(Item(img=sp, xy=(x, yy), cue=cue, dur=0.5, what="arrow label", anim="fade", pre=pre, gid=gid,
                              focusable=False))   # appears with its arrow

    for n in nodes:   # what the earlier scenes of this canvas already drew stays where it was
        i = labels.index(split_node(n)[0][:18])
        if split_node(n)[0].lower() in carry_n:
            node(i, True)
    for e, _p in valid:
        if e in carry_e:
            edge(e, True)
    own = [split_node(n)[0][:18] for n in scene["nodes"] if split_node(n)[0]]
    for e in scene.get("edges") or []:   # new things, in the order the voice explains them
        if e in by_edge and e not in carry_e:
            edge(e, False)
    for lab in own:
        if lab in labels:
            node(labels.index(lab), lab.lower() in carry_n)


def _points(g, scene, items):
    y = _heading_item(g, scene.get("on_screen"), items) + 6
    pts = [_clean(i) for i in scene.get("items") or [] if _clean(i)][:5]
    size = g["body"] * 1.4
    wd = g["x1"] - g["x0"]
    while size > 22 and sum(len(wrap(t, "semi", size, wd - 130)) * size * 1.25 + 52 + 18 for t in pts) > g["bot"] - y:
        size -= 2
    used = sum(len(wrap(t, "semi", size, wd - 130)) * size * 1.25 + 52 + 18 for t in pts)
    y += max(0, (g["bot"] - y - used) * 0.35)   # the list sits in the middle of the screen, not at the top
    for n, t in enumerate(pts):
        lines = wrap(t, "semi", size, wd - 130)
        h = int(len(lines) * size * 1.25 + 52)
        im = card2x(wd, h)
        col = (VIOLET, TEAL, AMBER, PINK, BLUE)[n % 5]
        d = ImageDraw.Draw(im)
        cy = (22 + h / 2) * SS
        d.ellipse([(22 + 26) * SS, cy - 28 * SS, (22 + 82) * SS, cy + 28 * SS], fill=(*col, 255))
        d.text(((22 + 54) * SS, cy), str(n + 1), font=font("bold", 30 * SS), fill=(14, 15, 20, 255), anchor="mm")
        f = font("semi", size * SS)
        for i, ln in enumerate(lines):
            d.text(((22 + 104) * SS, (22 + 26) * SS + i * size * 1.25 * SS), ln, font=f, fill=(*TEXT, 255))
        items.append(Item(img=_down(im), xy=(g["x0"] - 22, y - 22), cue=t, dur=0.9, what="bullet", anim="slide", gid=f"p:{n}",
                          box=(g["x0"], y, g["x1"], y + h), ring=True))
        y += h + 18


def _code(g, scene, items):
    y = _heading_item(g, scene.get("on_screen"), items)
    raw = str(scene.get("code") or "").replace("\t", "    ").rstrip().split("\n")[:16]
    lang = (str(scene.get("language") or "").lower()) or "code"
    wd = g["x1"] - g["x0"]
    size = max(14, min(wd / (0.62 * max(len(r) for r in raw)), (g["bot"] - y - 100) / (len(raw) * 1.5), g["body"] * 1.2))
    lh = size * 1.5
    h = int(len(raw) * lh + 84)
    im = card2x(wd, h, fill=(14, 15, 20), border=(60, 64, 80), r=18)
    d = ImageDraw.Draw(im)
    for n, c in enumerate((RED, AMBER, GREEN)):
        d.ellipse([(22 + 22 + n * 26) * SS, (22 + 20) * SS, (22 + 34 + n * 26) * SS, (22 + 32) * SS], fill=(*c, 255))
    d.text(((22 + wd - 24) * SS, (22 + 26) * SS), lang, font=font("mono", 17 * SS), fill=(*MUTED, 255), anchor="rm")
    items.append(Item(img=_down(im), xy=(g["x0"] - 22, y - 22), dur=0.7, what="code panel", anim="fade", focusable=False))
    f = font("mono", size * SS)
    for n, ln in enumerate(raw):
        runs, cx = [], 0
        sp = Image.new("RGBA", (int(wd * SS), int(lh * SS)), (0, 0, 0, 0))
        dd = ImageDraw.Draw(sp)
        for text, col in tokenize(ln, lang):
            dd.text((cx, 0), text, font=f, fill=col)
            cx += f.getlength(text)
        items.append(Item(img=_down(sp), xy=(g["x0"] + 26, y + 62 + n * lh), dur=min(1.6, 0.4 + 0.04 * len(ln)), what="code",
                          anim="wipe", gid=f"c:{n}", focusable=True))


def _statement(g, scene, items, title):
    big = _clean(scene.get("on_screen") or " ".join(str(scene.get("narration", "")).split()[:10]))
    wd = g["x1"] - g["x0"]
    lines, size = fit(big, "bold", wd, (g["bot"] - g["top"]) * 0.5, g["u"] * (0.105 if title else 0.085), 34, 1.18)
    h = int(len(lines) * size * 1.18)
    y = (g["top"] + g["bot"]) / 2 - h / 2 - (g["body"] * 1.2 if scene.get("items") else 0)
    if not title:   # a big object above the words, so the screen is a picture and not just a sentence
        kind = guess_icon(big + " " + str(scene.get("narration", "")))
        isz = int(g["u"] * (0.25 if g["short"] else 0.28))
        col = ICON_COLOR.get(kind, VIOLET)
        box = int(isz * 1.55)
        sp = Image.new("RGBA", (box * SS, box * SS), (0, 0, 0, 0))
        dd = ImageDraw.Draw(sp)
        dd.ellipse([box * SS * 0.08, box * SS * 0.08, box * SS * 0.92, box * SS * 0.92], fill=(*col, 34), outline=(*col, 120), width=3 * SS)
        dd.ellipse([box * SS * 0.2, box * SS * 0.2, box * SS * 0.8, box * SS * 0.8], fill=(*CARD_HI, 255), outline=(*col, 255), width=3 * SS)
        ic = icon2x(kind, int(isz * 0.62), col)
        sp.alpha_composite(ic, ((box * SS - ic.width) // 2, (box * SS - ic.height) // 2))
        top = max(g["top"], (g["top"] + g["bot"]) / 2 - (box + 30 + h) / 2)
        items.append(Item(img=_down(sp), xy=(g["w"] / 2 - box / 2, top), dur=0.9, what="box", anim="pop", focusable=False))
        y = top + box + 30
    im = Image.new("RGBA", (int(wd), h + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        d.text((wd / 2, i * size * 1.18), ln, font=font("bold", size), fill=(*TEXT, 255), anchor="ma")
    items.append(Item(img=im, xy=(g["x0"], y), dur=1.1, what="title", anim="rise", focusable=False))
    if not title:
        under = Image.new("RGBA", (int(wd * 0.5) * SS, 12 * SS), (0, 0, 0, 0))
        pts = _wobble([(6 * SS, 5 * SS), (under.width - 6 * SS, 7 * SS)], random.Random(3), 1.6 * SS, step=10 * SS)
        ImageDraw.Draw(under).line(pts, fill=(*AMBER, 255), width=5 * SS, joint="curve")
        items.append(Item(img=_down(under), xy=(g["w"] / 2 - wd * 0.25, y + h + 22), dur=0.6, what="underline", anim="wipe",
                          focusable=False))
    yy = y + h + 70
    for t in scene.get("items") or []:
        sp = tx(_clean(t), "semi", g["body"] * 0.95, MUTED)
        items.append(Item(img=sp, xy=(g["w"] / 2 - sp.width / 2, yy), dur=0.7, what="subtitle", anim="rise", focusable=False))
        yy += g["body"] * 1.5


# ---------- a data walkthrough (trace) and messages between components (flow) ----------
PTR_COLORS = (VIOLET, AMBER, TEAL, PINK)
MOVE_S = 0.55   # how long a pointer takes to slide to its next cell


def _ease(f):
    f = min(1.0, max(0.0, f))
    return f * f * (3 - 2 * f)


@lru_cache(maxsize=256)
def _cell_sprite(text, w, h, state):
    fill, border, ink = {"normal": (CARD, BORDER, TEXT), "active": (CARD_HI, VIOLET, TEXT), "found": ((22, 56, 40), GREEN, GREEN),
                         "out": ((20, 21, 27), (40, 43, 54), (92, 97, 110))}[state]
    im = card2x(w, h, fill=fill, border=border, r=14, pad=10, bw=3 if state in ("active", "found") else 2)
    size = h * 0.46 if len(text) <= 2 else min(h * 0.46, w * 0.84 / (0.62 * len(text)))
    ImageDraw.Draw(im).text(((10 + w / 2) * SS, (10 + h / 2) * SS), text, font=font("monob", size * SS), fill=(*ink, 255), anchor="mm")
    return _down(im)


def _step_items(items, steps, dur):
    """One invisible thing per step, so the steps are timed to the voice with everything else (and checked by the audit)."""
    items[-1].data["items"] = [Item(kind="step", cue=st["cue"], dur=dur, what="step", focusable=False) for st in steps]
    items.extend(items[-1].data["items"])


def _trace(g, scene, items):
    y = _heading_item(g, scene.get("on_screen"), items)
    cells = [_clean(c) for c in scene.get("cells") or []]
    n, wd = len(cells), g["x1"] - g["x0"]
    gap = 10 if n > 6 else 16
    cw = int(min(g["u"] * (0.19 if n <= 5 else 0.14), (wd - gap * (n - 1)) / n))
    ch = int(cw * 0.95)
    x0 = g["x0"] + (wd - (n * cw + (n - 1) * gap)) / 2
    cy = y + (g["u"] * 0.12 if g["short"] else 30)
    xs = [x0 + i * (cw + gap) for i in range(n)]
    for i, c in enumerate(cells):   # the array appears first, one cell after the other
        items.append(Item(img=_cell_sprite(c, cw, ch, "normal"), xy=(xs[i] - 10, cy - 10), dur=0.45, what="cell", anim="pop",
                          focusable=False))
    steps = [dict(st, cue=st.get("say")) for st in scene.get("steps") or []]
    items.append(Item(kind="trace", pre=True, focusable=False, what="trace", data={
        "cells": cells, "xs": xs, "cw": cw, "ch": ch, "cy": cy, "g": g, "steps": steps}))
    _step_items(items, steps, 0.6)


def _draw_trace(canvas, it, t):
    d, g = it.data, it.data["g"]
    steps, starts = d["steps"], it.starts
    k = max([i for i, s in enumerate(starts) if s <= t], default=-1)
    st = steps[k] if k >= 0 else {}
    xs, cw, ch, cy = d["xs"], d["cw"], d["ch"], d["cy"]
    for i, c in enumerate(d["cells"]):
        state = "found" if i in (st.get("found") or []) else "active" if i in (st.get("active") or []) else \
            "out" if i in (st.get("out") or []) else "normal"
        if state != "normal":
            _put(canvas, _cell_sprite(c, cw, ch, state), xs[i] - 10, cy - 10)
        idx = tx(str(i), "mono", max(14, ch * 0.2), MUTED)
        _put(canvas, idx, xs[i] + (cw - idx.width) / 2, cy + ch + 8)
    ptr_y = cy + ch + 8 + max(14, ch * 0.2) * 1.5 + 6
    names = []
    for s in steps:
        for p in s.get("pointers") or []:
            q = parse_pointer(p)
            if q and q[0] not in names:
                names.append(q[0])
    now = {q[0]: q[1] for q in map(parse_pointer, st.get("pointers") or []) if q}
    before = {q[0]: q[1] for q in map(parse_pointer, (steps[k - 1].get("pointers") or []) if k > 0 else []) if q}
    f = _ease((t - starts[k]) / MOVE_S) if k >= 0 else 1.0
    stack = {}
    for name in names:
        if name not in now:
            continue
        a = before.get(name, now[name])
        pos = a + (now[name] - a) * f
        x = xs[0] + pos * (cw + (xs[1] - xs[0] - cw)) + cw / 2 if len(xs) > 1 else xs[0] + cw / 2
        col = PTR_COLORS[names.index(name) % len(PTR_COLORS)]
        lvl = stack.setdefault(now[name], 0)
        stack[now[name]] += 1
        size = max(16, ch * 0.24)
        pill = pill_sprite(name, size, col)
        top = ptr_y + lvl * (pill.height + 6)
        arrow = Image.new("RGBA", (28 * SS, 20 * SS), (0, 0, 0, 0))
        ImageDraw.Draw(arrow).polygon([(14 * SS, 0), (26 * SS, 18 * SS), (2 * SS, 18 * SS)], fill=(*col, 255))
        arrow = _down(arrow)
        if lvl == 0:
            _put(canvas, arrow, x - arrow.width / 2, ptr_y - 2)
        _put(canvas, pill, x - pill.width / 2, top + (arrow.height if lvl == 0 else 0))
    ps = max(16, ch * 0.24)
    y = ptr_y + arrow_h(g) + max(1, max(stack.values(), default=1)) * (ps * 1.7 + 6) + 16 if names else ptr_y
    memo = [_clean(m) for m in st.get("memo") or []]
    if memo:
        lab = tx("remembered", "semi", g["body"] * 0.62, MUTED)
        _put(canvas, lab, g["x0"], y)
        cx, cyy = g["x0"], y + lab.height + 6
        for m in memo:
            pill = pill_sprite(m, max(16, g["body"] * 0.62), TEAL)
            if cx + pill.width > g["x1"]:
                cx, cyy = g["x0"], cyy + pill.height + 8
            _put(canvas, pill, cx, cyy)
            cx += pill.width + 10
        y = cyy + g["body"] * 1.6
    note = _clean(st.get("note") or "")
    if note and k >= 0:
        a = min(1.0, (t - starts[k]) / 0.35)
        lines, size = fit(note, "bold", g["x1"] - g["x0"] - 80, g["body"] * 3.2, g["body"] * 1.25, 22, 1.2)
        h = int(len(lines) * size * 1.2 + 40)
        card = card2x(g["x1"] - g["x0"], h, fill=CARD_HI, border=GREEN if st.get("found") else VIOLET)
        dd = ImageDraw.Draw(card)
        for i, ln in enumerate(lines):
            dd.text(((22 + (g["x1"] - g["x0"]) / 2) * SS, (22 + 20 + i * size * 1.2) * SS), ln, font=font("bold", size * SS),
                    fill=(*TEXT, 255), anchor="ma")
        _put(canvas, _fade(_down(card), a), g["x0"] - 22, y - 22)


def arrow_h(g):
    return 24


def _flow(g, scene, items):
    y = _heading_item(g, scene.get("on_screen"), items)
    nodes = [n for n in scene["nodes"] if split_node(n)[0]]
    labels = [split_node(n)[0][:18] for n in nodes]
    valid = [(e, parse_edge(e, nodes)) for e in scene.get("edges") or []]
    valid = [(e, p) for e, p in valid if p]
    tuples = [p for _e, p in valid]
    gf = dict(g, max_bw=int(g["max_bw"] * 0.7))   # smaller boxes leave room on the arrows for the data they carry
    boxes, rows, vertical = place_diagram(gf, tuples, len(nodes), y)
    routes = _routes(gf, boxes, rows, vertical, tuples, y)
    words = timeline.word_times(str(scene.get("narration", "")), 100.0)
    for i, nd in enumerate(nodes):
        l, t, r, b = boxes[i]
        sp, pad = iso_node_sprite(labels[i], guess_icon(labels[i], split_node(nd)[1]), int(r - l), int(b - t))
        items.append(Item(img=_fade(sp, 0.22), xy=(l - pad, t - pad), what="ghost", pre=True, focusable=False))
        items.append(Item(img=sp, xy=(l - pad, t - pad), cue=labels[i], dur=0.8, what="box", anim="pop", focusable=False))
    steps = []
    for (e, (i, j, label)), (pts, pos, anchor, _c) in zip(valid, routes):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        steps.append({"pts": pts, "pos": pos, "anchor": anchor, "label": _clean(label), "back": i > j,
                      "box": (int(min(xs)) - 26, int(min(ys)) - 26, int(max(xs)) + 26, int(max(ys)) + 26),
                      "cue": _spoken_later(words, 0.0, label, labels[j])[0] or label or labels[j]})
    items.append(Item(kind="flow", pre=True, focusable=False, what="flow", data={"steps": steps, "g": g}))
    _step_items(items, steps, 0.9)


def _draw_flow(canvas, it, t):
    steps, starts, g = it.data["steps"], it.starts, it.data["g"]
    size = max(15, int(g["body"] * 0.46))
    for k, st in enumerate(steps):
        if starts[k] > t:
            break
        cur = k + 1 >= len(starts) or starts[k + 1] > t
        col = AMBER if st["back"] else VIOLET
        done = (96, 165, 250) if not st["back"] else (200, 150, 70)
        link = Item(kind="link", pts=st["pts"], color=col if cur else done, box=st["box"])
        p = min(1.0, (t - starts[k]) / 0.9)
        _draw_link(canvas, link, _ease(p) if cur else 1.0, 0.0)
        pill = pill_sprite(st["label"] or str(k + 1), size, col if cur else done)
        badge = tx(str(k + 1), "bold", size * 0.95, (14, 15, 20))
        if cur and p < 1.0:   # the data travels with the dot
            x, yy = _point_at(st["pts"], _ease(p) * _plen(st["pts"]))
            sp = _glow(col)
            _put(canvas, sp, x - sp.width / 2, yy - sp.height / 2)
            _put(canvas, pill, x - pill.width / 2, yy - pill.height - 18)
            continue
        x, yy = st["pos"]
        px = {"l": x, "m": x - pill.width / 2, "r": x - pill.width}[st["anchor"][0]]
        py = {"t": yy, "m": yy - pill.height / 2, "b": yy - pill.height}[st["anchor"][1]]
        _put(canvas, pill, px, py)
        r = int(size * 0.8)
        dot = Image.new("RGBA", (2 * r * SS, 2 * r * SS), (0, 0, 0, 0))
        ImageDraw.Draw(dot).ellipse([0, 0, 2 * r * SS - 1, 2 * r * SS - 1], fill=(*(col if cur else done), 255))
        dot = _down(dot)
        _put(canvas, dot, px - r * 0.9, py - r * 0.9)
        _put(canvas, badge, px - r * 0.9 + (dot.width - badge.width) / 2, py - r * 0.9 + (dot.height - badge.height) / 2)


def build(scene, fmt, group=None):
    """The things drawn for one scene, in order. Those with pre=True were drawn by an earlier scene of the same canvas."""
    g, items, layout = _geom(fmt), [], scene.get("layout")
    if layout == "diagram" and _is_diagram(scene):
        _diagram(g, scene, items, group)
    elif layout == "trace" and len(scene.get("cells") or []) >= 2 and scene.get("steps"):
        _trace(g, scene, items)
    elif layout == "flow" and _is_diagram(dict(scene, layout="diagram")):
        _flow(g, scene, items)
    elif layout == "points" and scene.get("items"):
        _points(g, scene, items)
    elif layout == "code" and str(scene.get("code") or "").strip():
        _code(g, scene, items)
    else:
        _statement(g, scene, items, layout == "title")
    return items


def timed(items):
    return [it for it in items if not it.pre]


# ---------- the picture around the things ----------
@lru_cache(maxsize=8)
def background(fmt, kicker, handle, title):
    g = _geom(fmt)
    w, h = g["w"], g["h"]
    grad = Image.linear_gradient("L").resize((w, h))
    if title:
        im = Image.composite(Image.new("RGB", (w, h), (30, 16, 72)), Image.new("RGB", (w, h), (104, 52, 210)), grad)
        d = ImageDraw.Draw(im, "RGBA")   # the picture is plain RGB while shapes are blended on, so the alpha values really blend
        d.polygon([(w * 0.45, 0), (w, 0), (w, h * 0.5)], fill=(255, 255, 255, 16))
        d.polygon([(0, h * 0.55), (w * 0.8, h), (0, h)], fill=(255, 255, 255, 10))
        d.polygon([(w * 0.2, 0), (w * 0.55, 0), (0, h * 0.3), (0, h * 0.12)], fill=(0, 0, 0, 40))
    else:
        im = Image.composite(Image.new("RGB", (w, h), BG2), Image.new("RGB", (w, h), BG), grad)
        d = ImageDraw.Draw(im, "RGBA")
        for yy in range(30, h, 54):
            for xx in range(30, w, 54):
                d.ellipse([xx - 1, yy - 1, xx + 1, yy + 1], fill=(255, 255, 255, 14))
    im = im.convert("RGBA")
    k = _clean(kicker).upper()
    if k:
        _put(im, pill_sprite(k, int(g["body"] * 0.5), VIOLET if not title else (230, 220, 255)), g["x0"], 46 if g["short"] else 34)
    hd = _clean(handle)
    if hd:
        sp = tx(hd, "semi", g["body"] * 0.5, MUTED if not title else (210, 200, 245))
        _put(im, sp, g["x1"] - sp.width, g["h"] - 52)
    return im


@lru_cache(maxsize=4)
def _dim(w, h):
    return Image.new("RGBA", (w, h), (*BG2, 150))


@lru_cache(maxsize=8)
def _glow(color):
    s = 44 * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([s * 0.28, s * 0.28, s * 0.72, s * 0.72], fill=(*color, 255))
    im = im.filter(ImageFilter.GaussianBlur(7 * SS))
    ImageDraw.Draw(im).ellipse([s * 0.42, s * 0.42, s * 0.58, s * 0.58], fill=(255, 255, 255, 255))
    return _down(im)


def _point_at(pts, dist):
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if dist <= seg:
            k = dist / seg if seg else 0
            return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
        dist -= seg
    return pts[-1]


def _draw_link(canvas, it, f, t0):
    x0, y0, x1, y1 = it.box
    part, _tip = _upto([it.pts], f)
    if not part or len(part[0]) < 2:
        return
    w, h = x1 - x0, y1 - y0
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pts = [((x - x0) * SS, (y - y0) * SS) for x, y in part[0]]
    d.line(pts, fill=(*it.color, 255), width=int(4.5 * SS), joint="curve")
    r = 2.2 * SS
    d.ellipse([pts[0][0] - r, pts[0][1] - r, pts[0][0] + r, pts[0][1] + r], fill=(*it.color, 255))
    if f >= 0.97:
        (ax, ay), (bx, by) = pts[-2], pts[-1]
        ln = math.hypot(bx - ax, by - ay) or 1
        ux, uy, hl = (bx - ax) / ln, (by - ay) / ln, 19 * SS
        d.polygon([(bx, by), (bx - hl * ux + hl * 0.55 * uy, by - hl * uy - hl * 0.55 * ux),
                   (bx - hl * ux - hl * 0.55 * uy, by - hl * uy + hl * 0.55 * ux)], fill=(*it.color, 255))
    _put(canvas, _down(im), x0, y0)


def _packet(canvas, it, t):
    """A dot that travels along the arrow while it is being explained."""
    total = _plen(it.pts)
    x, y = _point_at(it.pts, ((t % 1.7) / 1.7) * total)
    sp = _glow(it.color)
    _put(canvas, sp, x - sp.width / 2, y - sp.height / 2)


def _dash_ring(canvas, box, t, color=VIOLET):
    l, tp, r, b = box
    pad = 12
    W, H = int(r - l + 2 * pad), int(b - tp + 2 * pad)
    rad = 24
    x0, y0, x1, y1 = pad, pad, pad + (r - l), pad + (b - tp)
    pts = []
    for cx, cy, a0 in ((x1 - rad, y0 + rad, -90), (x1 - rad, y1 - rad, 0), (x0 + rad, y1 - rad, 90), (x0 + rad, y0 + rad, 180)):
        pts += [(cx + rad * math.cos(math.radians(a0 + s * 18)), cy + rad * math.sin(math.radians(a0 + s * 18))) for s in range(6)]
    pts.append(pts[0])
    im = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    dash, gap, off, run = 14, 9, (t * 38) % 23, 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        pos = 0.0
        while pos < seg:
            phase = (run + pos + off) % (dash + gap)
            step = min(seg - pos, (dash - phase) if phase < dash else (dash + gap - phase))
            if phase < dash:
                p0 = (a[0] + (b[0] - a[0]) * pos / seg, a[1] + (b[1] - a[1]) * pos / seg)
                p1 = (a[0] + (b[0] - a[0]) * (pos + step) / seg, a[1] + (b[1] - a[1]) * (pos + step) / seg)
                d.line([(p0[0] * SS, p0[1] * SS), (p1[0] * SS, p1[1] * SS)], fill=(*color, 255), width=3 * SS)
            pos += max(step, 0.5)
        run += seg
    _put(canvas, _down(im), l - pad, tp - pad)


def draw_item(canvas, it, f, t0=0.0):
    if f <= 0:
        return
    if it.kind == "link":
        _draw_link(canvas, it, f, t0)
        return
    if it.kind in ("trace", "flow", "step"):
        return
    sp, (x, y) = it.img, it.xy
    if f >= 1:
        _put(canvas, sp, x, y + (3.5 * math.sin(t0 * 1.7 + x * 0.013) if it.what == "box" else 0))   # blocks float a little
        return
    a = min(1.0, f * 1.6)
    if it.anim == "pop":
        s = 0.86 + 0.14 * _back(f)
        r = sp.resize((max(1, int(sp.width * s)), max(1, int(sp.height * s))), Image.BILINEAR)
        _put(canvas, _fade(r, a), x + (sp.width - r.width) / 2, y + (sp.height - r.height) / 2 + (1 - f) * 16)
    elif it.anim == "slide":
        _put(canvas, _fade(sp, a), x - (1 - f) * 90, y)
    elif it.anim == "rise":
        _put(canvas, _fade(sp, a), x, y + (1 - f) * 36)
    elif it.anim == "wipe":
        _put(canvas, sp.crop((0, 0, max(1, int(sp.width * f)), sp.height)), x, y)
    else:
        _put(canvas, _fade(sp, a), x, y)


@lru_cache(maxsize=4)
def _dust(w, h):
    rnd = random.Random(7)
    return [(rnd.random() * w, rnd.random() * h, 0.6 + rnd.random() * 1.6, 8 + rnd.random() * 18) for _ in range(22)]


def _ambient(canvas, t, g):
    """Slow specks of light drifting up the screen, so even a quiet moment is alive."""
    w, h = g["w"], g["h"]
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x, y0, r, sp in _dust(w, h):
        y = (y0 - t * sp) % h
        a = int(40 + 30 * math.sin(t * 0.9 + x))
        rr = 2 + r * 2
        d.ellipse([x + 12 * math.sin(t * 0.4 + y0) - rr, y - rr, x + 12 * math.sin(t * 0.4 + y0) + rr, y + rr], fill=(167, 139, 250, a))
    canvas.alpha_composite(layer)


def _camera(canvas, t, length):
    """A slow push-in over the scene (up to 4%), so the picture never sits perfectly still."""
    z = 1 + 0.04 * min(1.0, t / max(length, 1.0))
    w, h = canvas.size
    cw, ch = w / z, h / z
    box = ((w - cw) / 2, (h - ch) * 0.45, (w + cw) / 2, (h - ch) * 0.45 + ch)
    return canvas.resize((w, h), Image.BILINEAR, box=box)


# ---------- captions ----------
def caption_chunks(words, length, max_words=4):
    """[(text, start, end)]: two to four words at a time, cut at punctuation, timed to the voice."""
    groups, cur = [], []
    for w, s, _e in words:
        cur.append((w, s))
        if len(cur) >= max_words or re.search(r"[,.;:!?…]$", w):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    if len(groups) > 1 and len(groups[-1]) == 1 and len(groups[-2]) < max_words + 1:
        last = groups.pop()
        groups[-1] += last
    out = []
    for i, c in enumerate(groups):
        end = groups[i + 1][0][1] if i + 1 < len(groups) else length
        text = " ".join(w for w, _s in c).replace("...", "").replace("…", "").strip(" ")
        out.append((text, 0.0 if i == 0 else c[0][1], end))
    return out


@lru_cache(maxsize=512)
def caption_sprite(text, fmt):
    g = _geom(fmt)
    size = g["u"] * (0.047 if g["short"] else 0.050)
    lines = wrap(text, "bold", size, g["x1"] - g["x0"] - 80)[:2]
    f = font("bold", size * SS)
    parts = []
    for ln in lines:
        wd, ht = int(f.getlength(ln)) + 44 * SS, int(size * 1.55 * SS)
        im = Image.new("RGBA", (wd, ht), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, wd - 1, ht - 1], 14 * SS, fill=(*PURPLE, 245))
        d.text((wd / 2, ht / 2), ln, font=f, fill=(255, 255, 255, 255), anchor="mm")
        parts.append(_down(im))
    total = sum(p.height for p in parts) + 8 * (len(parts) - 1)
    return parts, total


# ---------- one scene ----------
def _focus(timed_items, slots, t):
    best = None
    for i, (it, (s, _e)) in enumerate(zip(timed_items, slots)):
        if it.focusable and s <= t < s + HOLD_S and (best is None or s >= slots[best][0]):
            best = i
    return best


def render_scene(scene, fmt, length, wd, n, count, kicker="", handle="", captions=True, fps=DRAW_FPS, audio=None, group=None):
    """Draw one scene to its voice: returns ([(png, seconds)], [(start, end)] of every timed thing)."""
    g = _geom(fmt)
    items = build(scene, fmt, group)
    tm = timed(items)
    index = {id(it): k for k, it in enumerate(tm)}
    words, _measured = timeline.voice_words(str(scene.get("narration", "")), length, audio)
    slots = timeline.schedule([{"cue": it.cue, "dur": it.dur} for it in tm], words, length, min_gap=0.4)   # animations may overlap
    dyn = [it for it in items if it.kind in ("trace", "flow")]
    for it in dyn:   # each step happens when the voice says it (scheduled above with everything else)
        it.starts = [slots[index[id(st)]][0] for st in it.data["items"]]
    chunks = caption_chunks(words, length) if captions else []
    bg = background(fmt, kicker, handle, scene.get("layout") == "title")
    dim = _dim(g["w"], g["h"])
    frames, last = [], None
    for k in range(max(1, int(round(length * fps)))):
        t = k / fps
        prog = timeline.progress(slots, t)
        fi = _focus(tm, slots, t) if scene.get("layout") != "title" else None
        cap = next((c for c, (_x, s, e) in enumerate(chunks) if s <= t < e), len(chunks) - 1 if chunks and t >= chunks[-1][1] else -1)
        moving = fi is not None and (tm[fi].kind == "link" or tm[fi].ring)
        dkey = tuple((sum(1 for a in it.starts if a <= t), int(t * 12) if any(a <= t < a + 1.3 for a in it.starts) else 0)
                     for it in dyn)
        key = (tuple(round(f, 2) for f in prog), fi, int(t * 12), cap, dkey)   # always a little motion: floating blocks, drifting dust, a slow camera
        if key == last:
            frames[-1][1] += 1 / fps
            continue
        last = key
        canvas = bg.copy()
        _ambient(canvas, t, g)
        f_of = lambda it: 1.0 if it.pre else prog[index[id(it)]]
        for it in items:
            if not it.head:
                draw_item(canvas, it, f_of(it), t)
        if scene.get("layout") == "diagram":   # data keeps flowing along every arrow that is already drawn
            for q, it in enumerate(i for i in items if i.kind == "link" and f_of(i) >= 1):
                _packet(canvas, it, t + q * 0.55)
        if fi is not None:
            fo = tm[fi]
            keep = {fo.gid, *fo.also}
            canvas.alpha_composite(dim)
            for it in items:
                if it.gid in keep and not it.head:
                    draw_item(canvas, it, f_of(it), t)
            if fo.kind == "link" and prog[fi] >= 1:
                _packet(canvas, fo, t - slots[fi][0])
            if fo.ring and prog[fi] >= 0.6:
                _dash_ring(canvas, fo.box, t)
        for it in dyn:
            (_draw_trace if it.kind == "trace" else _draw_flow)(canvas, it, t)
        if scene.get("layout") != "title":
            canvas = _camera(canvas, t, length)
        for it in items:
            if it.head:
                draw_item(canvas, it, f_of(it), t)
        if cap >= 0:
            parts, total = caption_sprite(chunks[cap][0], fmt)
            y = g["cap_cy"] - total / 2
            for p in parts:
                _put(canvas, p, (g["w"] - p.width) / 2, y)
                y += p.height + 8
        png = Path(wd) / f"ex-{n:02d}-{len(frames):04d}.png"
        canvas.convert("RGB").save(png, compress_level=1)
        frames.append([png, 1 / fps])
    return [(p, d) for p, d in frames], slots


def still(scene, fmt, kicker="", handle="", group=None, at=None):
    """The scene as it looks once everything is drawn (or at second `at`), for previews and tests."""
    import tempfile
    length = 12.0
    with tempfile.TemporaryDirectory() as d:
        frames, _slots = render_scene(scene, fmt, length, d, 0, 1, kicker, handle, True, fps=4, group=group)
        k = min(len(frames) - 1, int((at if at is not None else length - 1) * 4))
        total, idx = 0.0, 0
        for i, (_p, dur) in enumerate(frames):
            total += dur
            if total > (at if at is not None else length - 1):
                idx = i
                break
        else:
            idx = len(frames) - 1
        return Image.open(frames[idx][0]).convert("RGB")


def render(scenes, out_path, fmt, workdir, audio=None, handle="", kicker="", captions=True, progress=None, redo=None):
    from . import blackboard
    import sys
    return blackboard.render(scenes, out_path, fmt, workdir, audio=audio, handle=handle, kicker=kicker, captions=captions,
                             progress=progress, redo=redo, engine=sys.modules[__name__])


def thumbnail(script, kicker, handle, out_path):
    """The 16:9 thumbnail: the same purple opening card the video starts with."""
    scene = {"layout": "title", "on_screen": script.get("thumbnail_text") or script["title"], "items": [script["title"]],
             "narration": script["title"]}
    still(scene, "long", kicker, handle, at=3.0).resize((1280, 720), Image.LANCZOS).save(out_path, "PNG")
    return out_path
