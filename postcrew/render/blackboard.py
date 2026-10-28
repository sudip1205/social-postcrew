"""Blackboard "draw and explain" video: a chalkboard on which the picture is drawn by hand while the voice explains it.

Every scene becomes a list of things to draw (heading, boxes, arrows, labels, bullets, code lines). Their start times come from
the voice (render/timeline.py): each thing begins when the narrator says its name, and a chalk stick follows the stroke.
Frames are drawn with Pillow at 15 fps (identical frames are written once) and put together with ffmpeg; the audio is the voice
generated before, scene by scene.
"""
import json
import math
import random
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from . import timeline
from .scenes import FORMATS, _exit_point, parse_edge, place_diagram, split_captions, split_node
from .theme import FONT_DIR
from .video import ENC, FPS, VideoError, _run, _scene_lengths, assemble, probe

DRAW_FPS = 15
BOARD = (31, 54, 46)
WHITE, YELLOW, BLUE, PINK, GREEN = (243, 241, 232), (246, 214, 96), (140, 200, 235), (244, 166, 184), (165, 222, 165)
CHALK_FONTS = [
    "/System/Library/Fonts/Supplemental/Chalkboard.ttc", "/System/Library/Fonts/Supplemental/ChalkboardSE.ttc",
    "/System/Library/Fonts/MarkerFelt.ttc", "/usr/share/fonts/truetype/comic-neue/ComicNeue-Bold.ttf",
    "/usr/share/fonts/truetype/patrick-hand/PatrickHand-Regular.ttf", "/usr/share/fonts/truetype/humor-sans/Humor-Sans.ttf",
    "C:/Windows/Fonts/segoepr.ttf", "C:/Windows/Fonts/comic.ttf",
]
_SWAP = {"→": "->", "←": "<-", "≤": "<=", "≥": ">=", "≈": "~", "✓": "ok", "∞": "inf", "—": "-", "“": '"', "”": '"', "’": "'"}


def _clean(s):
    return "".join(_SWAP.get(c, c) for c in str(s or "")).strip()


@lru_cache(maxsize=None)
def chalk_font(size, mono=False):
    size = int(round(size))
    if mono:
        return ImageFont.truetype(str(FONT_DIR / "JetBrainsMono-Bold.ttf"), size)
    for p in CHALK_FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.truetype(str(FONT_DIR / "Inter-Bold.ttf"), size)   # no hand-written font on this machine


# ---------- the board ----------
@lru_cache(maxsize=4)
def _board(w, h):
    base = Image.new("RGB", (w, h), BOARD)
    smudge = Image.effect_noise((w // 6 + 1, h // 6 + 1), 38).resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(14))
    img = Image.composite(Image.new("RGB", (w, h), (70, 102, 88)), base, smudge.point(lambda v: max(0, v - 118) // 3))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w - 1, h - 1), outline=(122, 86, 52), width=16)
    d.rectangle((16, 16, w - 17, h - 17), outline=(78, 56, 34), width=4)
    return img


@lru_cache(maxsize=4)
def _chalk_noise(w, h):
    return Image.effect_noise((w, h), 55).point(lambda v: 150 + v * 105 // 255)


def _geom(fmt):
    w, h = FORMATS[fmt]
    short = h > w
    u = w if short else h
    cap_bot, cap_h = h * (0.83 if short else 0.90), h * (0.14 if short else 0.19)
    return {"w": w, "h": h, "short": short, "u": u, "x0": 72 if short else 110, "x1": w - (72 if short else 110),
            "top": 200 if short else 150, "bot": cap_bot - cap_h - (40 if short else 30), "cap_top": cap_bot - cap_h,
            "cap_bot": cap_bot, "body": u * (0.042 if short else 0.055), "lw": max(4.0, u * 0.0058)}


# ---------- things that can be drawn ----------
def _plen(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def _upto(strokes, f):
    total, target, out, tip = sum(_plen(s) for s in strokes), f * sum(_plen(s) for s in strokes), [], None
    for s in strokes:
        if target <= 0:
            break
        n = _plen(s)
        if target >= n:
            out.append(s)
            tip, target = s[-1], target - n
            continue
        cut = [s[0]]
        for a, b in zip(s, s[1:]):
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            if target <= seg:
                k = target / seg if seg else 0
                cut.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
                break
            cut.append(b)
            target -= seg
        out.append(cut)
        tip = cut[-1]
        break
    return out, tip


def _wobble(pts, rnd, amp, step=12):
    """The polyline resampled with a small hand-drawn waver."""
    ph, out, d = [rnd.uniform(0, 6.28) for _ in range(2)], [], 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        ln = math.hypot(x1 - x0, y1 - y0)
        if not ln:
            continue
        n, nx, ny = max(1, int(ln // step)), -(y1 - y0) / ln, (x1 - x0) / ln
        for k in range(n):
            t = k / n
            o = amp * (math.sin((d + ln * t) * 0.041 + ph[0]) + 0.5 * math.sin((d + ln * t) * 0.113 + ph[1]))
            out.append((x0 + (x1 - x0) * t + nx * o, y0 + (y1 - y0) * t + ny * o))
        d += ln
    return out + [pts[-1]]


class Strokes:
    what = ""
    """Chalk strokes drawn one after the other (a box, an arrow with its head, an underline, a bullet)."""

    def __init__(self, strokes, color, width, cue=None, dur=0.6, seed=0):
        rnd = random.Random(seed * 7919 + 13)
        self.color, self.cue, self.dur = color, cue, dur
        self.passes = [([_wobble(s, rnd, width * 0.35) for s in strokes], width),
                       ([_wobble(s, rnd, width * 0.5) for s in strokes], width * 0.55)]

    def draw(self, get, f):
        d, tip = ImageDraw.Draw(get(self.color)), None
        for strokes, width in self.passes:
            part, t = _upto(strokes, f)
            tip = tip or t
            for pts in part:
                if len(pts) > 1:
                    d.line(pts, fill=255, width=int(round(width)), joint="curve")
                    r = width / 2
                    for x, y in (pts[0], pts[-1]):
                        d.ellipse((x - r, y - r, x + r, y + r), fill=255)
        return tip if f < 1 else None


class Text:
    what = ""
    """Chalk writing, revealed from left to right line by line."""

    def __init__(self, lines, font, color, x, y, size, anchor="lt", cue=None, dur=None, lh=1.25):
        self.color, self.cue = color, cue
        sw = max(1, int(size / 26))
        widths = [font.getlength(ln) for ln in lines]
        total_w, total_h = max(widths or [0]), len(lines) * size * lh
        top = y - (total_h / 2 if anchor[1] == "m" else total_h if anchor[1] == "b" else 0)
        self.parts = []
        for k, (ln, wd) in enumerate(zip(lines, widths)):
            left = {"l": x, "m": x - wd / 2, "r": x - wd}[anchor[0]]
            bb = font.getbbox(ln or " ", stroke_width=sw)
            mask = Image.new("L", (int(bb[2]) + 4, int(bb[3]) + 4), 0)
            ImageDraw.Draw(mask).text((0, 0), ln, font=font, fill=255, stroke_width=sw, stroke_fill=255)
            self.parts.append((left, top + k * size * lh, mask, max(1.0, wd)))
        n = sum(len(ln) for ln in lines)
        self.dur = dur if dur is not None else min(2.4, max(0.5, 0.05 * n))

    def draw(self, get, f):
        total = sum(p[3] for p in self.parts)
        target, tip, m = f * total, None, get(self.color)
        for x, y, mask, wd in self.parts:
            take = min(wd, max(0.0, target))
            target -= wd
            if take <= 0:
                continue
            box = (int(x), int(y), int(x) + int(min(mask.width, take + 4)), int(y) + mask.height)
            crop = mask.crop((0, 0, box[2] - box[0], mask.height))
            m.paste(ImageChops.lighter(m.crop(box), crop), box)
            tip = (x + take, y + mask.height * 0.6)
            if take < wd:
                break
        return tip if f < 1 else None


# ---------- layout ----------
def _wrap(text, font, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}".strip()
            if not cur or font.getlength(trial) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _fit(text, max_w, max_h, start, lo, lh=1.25):
    size = start
    while True:
        f = chalk_font(size)
        lines = _wrap(text, f, max_w)
        if (max(f.getlength(ln) for ln in lines) <= max_w and len(lines) * size * lh <= max_h) or size <= lo:
            return lines, size, f
        size -= 2


def _box_pts(l, t, r, b, k=14):
    return [(l + k * 3, t), (r - k, t), (r, t + k), (r, b - k), (r - k, b), (l + k, b), (l, b - k), (l, t + k),
            (l + k, t), (l + k * 3, t + 2)]


def _circle(cx, cy, rad, turns=1.15, n=18):
    return [(cx + rad * math.cos(-1.2 + 6.283 * turns * i / n), cy + rad * math.sin(-1.2 + 6.283 * turns * i / n))
            for i in range(n + 1)]


def _arrow(pts, color, width, **kw):
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    ln = math.hypot(x1 - x0, y1 - y0) or 1
    ux, uy, hl = (x1 - x0) / ln, (y1 - y0) / ln, width * 5.5
    head = [[(x1, y1), (x1 - hl * (ux * math.cos(a) - uy * math.sin(a)), y1 - hl * (uy * math.cos(a) + ux * math.sin(a)))]
            for a in (0.5, -0.5)]
    return Strokes([pts] + head, color, width, **kw)


def _tag(item, what):
    item.what = what
    return item


def _heading(g, text, items):
    text = _clean(text)
    if not text:
        return g["top"]
    lines, size, f = _fit(text, g["x1"] - g["x0"], (g["bot"] - g["top"]) * 0.2, g["body"] * 1.5, 28)
    items.append(Text(lines, f, YELLOW, g["x0"], g["top"], size))
    y = g["top"] + len(lines) * size * 1.25
    wd = max(f.getlength(ln) for ln in lines)
    items.append(Strokes([[(g["x0"], y + 2), (g["x0"] + wd, y + 8)]], YELLOW, g["lw"], dur=0.4, seed=len(items)))
    return y + 36


def _routes(g, boxes, rows, vertical, edges, y):
    """For every edge: (points, label position, label anchor); a hop over other boxes goes round the outside."""
    lvl = {i: lv for lv, row in enumerate(rows) for i in row}
    pairs = {(i, j) for i, j, _l in edges}
    out, bypass = [], 0
    for i, j, _label in edges:
        a, b = boxes[i], boxes[j]
        if abs(lvl[i] - lvl[j]) > 1:
            bypass += 1
            if vertical:
                xr = g["x1"] + 14 + 26 * bypass
                ya, yb = (a[1] + a[3]) / 2, (b[1] + b[3]) / 2
                out.append(([(a[2], ya), (xr, ya), (xr, yb), (b[2], yb)], (xr - 12, (ya + yb) / 2), "rm", PINK))
            else:
                def blocked(box, up):
                    return any(o is not box and o[0] < box[2] and o[2] > box[0] and (o[3] <= box[1] if up else o[1] >= box[3])
                               for o in boxes.values())
                over = not (blocked(a, True) or blocked(b, True)) or (blocked(a, False) or blocked(b, False))
                xa, xb = (a[0] + a[2]) / 2, (b[0] + b[2]) / 2
                if over:
                    yt = max(y + 8, min(bx[1] for bx in boxes.values()) - 34 - 30 * bypass)
                    ya, yb = a[1], b[1]
                else:
                    yt = min(g["bot"] - 8, max(bx[3] for bx in boxes.values()) + 34 + 30 * bypass)
                    ya, yb = a[3], b[3]
                out.append(([(xa, ya), (xa, yt), (xb, yt), (xb, yb)], ((xa + xb) / 2, yt - 8 if over else yt + 8),
                            "mb" if over else "mt", PINK))
            continue
        ca, cb = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        dx, dy = cb[0] - ca[0], cb[1] - ca[1]
        norm = math.hypot(dx, dy) or 1
        back = (j, i) in pairs and i > j   # an answer going back runs beside the request, not over it
        off = 16 if (j, i) in pairs else 0
        ox, oy = -dy / norm * off, dx / norm * off
        p0, p1 = _exit_point(a, (cb[0] + ox, cb[1] + oy)), _exit_point(b, (ca[0] + ox, ca[1] + oy))
        p0, p1 = (p0[0] + ox, p0[1] + oy), (p1[0] + ox, p1[1] + oy)
        mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
        if off:
            pos, anchor = (mx + (-dy / norm) * 34, my + (dx / norm) * 34), "mm"
        elif abs(dx) >= abs(dy):   # a mostly horizontal arrow: the label sits above it
            pos, anchor = (mx, my - 14), "mb"
        else:
            pos, anchor = (mx + 16, my), "lm"
        out.append(([p0, p1], pos, anchor, PINK if back else BLUE))
    return out


def build(scene, fmt, group=None):
    """The things to draw for one scene, in order: [Text | Path] each with a `cue` (words that say when) and a `dur`."""
    g, items = _geom(fmt), []
    layout, shown = scene.get("layout"), _clean(scene.get("on_screen"))
    nodes = [_clean(split_node(n)[0])[:18] for n in (scene.get("nodes") or []) if _clean(split_node(n)[0])][:6]
    width = g["x1"] - g["x0"]
    if layout == "diagram" and len(nodes) >= 2:
        y = _heading(g, shown, items)
        edges = [e for e in (parse_edge(x, nodes) for x in (scene.get("edges") or [])) if e][:8]
        boxes, rows, vertical = place_diagram(g, edges, len(nodes), y)
        drawn = set()

        def box(i):
            if i in drawn:
                return
            drawn.add(i)
            l, t, r, b = boxes[i]
            items.append(_tag(Strokes([_box_pts(l, t, r, b)], WHITE, g["lw"], cue=nodes[i], dur=0.7, seed=len(items)), "box"))
            lines, size, f = _fit(nodes[i], r - l - 28, b - t - 16, g["body"], 14, 1.15)
            items.append(_tag(Text(lines, f, WHITE, (l + r) / 2, (t + b) / 2, size, "mm", cue=nodes[i], dur=0.45, lh=1.15), "box label"))

        small = g["body"] * 0.72
        for k, ((i, j, label), (pts, pos, anchor, color)) in enumerate(zip(edges, _routes(g, boxes, rows, vertical, edges, y))):
            box(i)
            box(j)
            items.append(_tag(_arrow(pts, color, g["lw"], cue=label or nodes[j], dur=0.6, seed=len(items)), "arrow"))
            if label:
                items.append(_tag(Text([_clean(label)], chalk_font(small), color, pos[0], pos[1], small, anchor, cue=label, dur=0.4), "arrow label"))
        for i in range(len(nodes)):
            box(i)
    elif layout == "points" and scene.get("items"):
        y = _heading(g, shown, items)
        pts = [_clean(i) for i in scene["items"] if _clean(i)][:5]
        size = g["body"] * 1.15
        while size > 22 and sum(len(_wrap(t, chalk_font(size), width - 60)) for t in pts) * size * 1.35 > g["bot"] - y:
            size -= 2
        for t in pts:
            lines = _wrap(t, chalk_font(size), width - 60)
            items.append(_tag(Strokes([_circle(g["x0"] + 14, y + size * 0.62, size * 0.17)], PINK, g["lw"], cue=t, dur=0.25, seed=len(items)), "bullet"))
            items.append(_tag(Text(lines, chalk_font(size), WHITE, g["x0"] + 50, y, size, cue=t), "bullet text"))
            y += len(lines) * size * 1.25 + size * 0.2
    elif layout == "code" and (scene.get("code") or "").strip():
        y = _heading(g, shown, items)
        code = [ln.rstrip().replace("\t", "    ") for ln in scene["code"].strip("\n").split("\n")][:18]
        cols = max(len(ln) for ln in code)
        size = max(14, min(width / (0.62 * max(cols, 1)), (g["bot"] - y - 40) / (len(code) * 1.35), g["body"] * 0.95))
        f = chalk_font(size, mono=True)
        height = len(code) * size * 1.35 + 36
        items.append(Strokes([_box_pts(g["x0"], y, g["x1"], y + height, 10)], WHITE, g["lw"] * 0.7, dur=0.8, seed=len(items)))
        for k, ln in enumerate(code):
            items.append(Text([ln or " "], f, BLUE, g["x0"] + 24, y + 18 + k * size * 1.35, size, dur=min(1.4, 0.3 + 0.03 * len(ln))))
    else:   # title and statement: one big sentence, with the key words under it for a title
        big = _clean(shown or " ".join(str(scene.get("narration", "")).split()[:10]))
        lines, size, f = _fit(big, width, (g["bot"] - g["top"]) * 0.55, g["body"] * (2.0 if g["short"] else 2.3), 30)
        mid = (g["top"] + g["bot"]) / 2 - (g["body"] if layout == "title" and scene.get("items") else 0)
        items.append(Text(lines, f, YELLOW if layout == "title" else WHITE, g["w"] / 2, mid, size, "mm"))
        wd = max(f.getlength(ln) for ln in lines)
        yy = mid + len(lines) * size * 0.625 + 8
        items.append(Strokes([[(g["w"] / 2 - wd / 2, yy), (g["w"] / 2 + wd / 2, yy + 6)]], YELLOW, g["lw"], dur=0.5, seed=len(items)))
        for k, t in enumerate(scene.get("items") or []):
            items.append(Text([_clean(t)], chalk_font(g["body"]), BLUE, g["w"] / 2, yy + 30 + k * g["body"] * 1.4, g["body"], "mt", cue=t))
    return items


# ---------- frames ----------
def _mask(masks, size, color):
    if color not in masks:
        masks[color] = Image.new("L", size, 0)
    return masks[color]


def _static(g, kicker, handle):
    """The kicker (top left) and the handle (bottom right), always on the board."""
    masks, size = {}, (g["w"], g["h"])
    for text, color, px, py, anchor, sz in ((_clean(kicker).upper(), YELLOW, g["x0"], 52, "lt", g["body"] * 0.62),
                                            (_clean(handle), BLUE, g["x1"], g["h"] - 64, "rb", g["body"] * 0.55)):
        if text:
            t = Text([text], chalk_font(sz), color, px, py, sz, anchor)
            t.draw(lambda c: _mask(masks, size, c), 1.0)
    return masks


def _caption(img, g, text):
    if not text:
        return
    d = ImageDraw.Draw(img)
    size = g["body"] * 0.95
    font = ImageFont.truetype(str(FONT_DIR / "Inter-Bold.ttf"), int(size))
    lines = _wrap(text, font, g["x1"] - g["x0"])[:3]
    y = g["cap_bot"] - len(lines) * size * 1.25
    for k, ln in enumerate(lines):
        d.text((g["w"] / 2, y + k * size * 1.25), ln, font=font, fill=(250, 248, 240), anchor="ma", stroke_width=4, stroke_fill=(14, 26, 22))


def _compose(g, masks, tip, caption):
    img = _board(g["w"], g["h"]).copy()
    noise = _chalk_noise(g["w"], g["h"])
    for color, m in masks.items():
        img.paste(color, mask=ImageChops.multiply(m, noise))
    if tip:   # the chalk stick that is drawing
        d = ImageDraw.Draw(img)
        s = g["lw"]
        d.line((tip[0] + s * 1.5, tip[1] - s * 2.6, tip[0] + s * 7, tip[1] - s * 11), fill=(236, 230, 214), width=int(s * 2.4))
        d.ellipse((tip[0] - s * 0.6, tip[1] - s * 0.6, tip[0] + s * 0.9, tip[1] + s * 0.9), fill=WHITE)
    _caption(img, g, caption)
    return img


def still(scene, fmt, kicker="", handle="", caption=""):
    """The scene completely drawn (thumbnails, tests, previews)."""
    g, masks = _geom(fmt), _static(_geom(fmt), kicker, handle)
    for it in build(scene, fmt):
        it.draw(lambda c: _mask(masks, (g["w"], g["h"]), c), 1.0)
    return _compose(g, masks, None, caption)


def thumbnail(script, kicker, handle, out_path):
    scene = {"layout": "title", "on_screen": script.get("thumbnail_text") or script["title"], "items": [script["title"]]}
    still(scene, "long", kicker, handle).resize((1280, 720), Image.LANCZOS).save(out_path, "PNG")
    return out_path


def render_scene(scene, fmt, length, wd, n, count, kicker="", handle="", captions=True, fps=DRAW_FPS, audio=None, group=None):
    """Draw one scene against its voice: returns ([(png, seconds)], [(start, end)] of every drawn thing). `audio`: this scene's
    voice file; with it the word times are measured on the real voice instead of estimated."""
    g = _geom(fmt)
    size = (g["w"], g["h"])
    items = build(scene, fmt)
    narration = str(scene.get("narration", ""))
    words, _measured = timeline.voice_words(narration, length, audio)
    slots = timeline.schedule([{"cue": it.cue, "dur": it.dur} for it in items], words, length)
    chunks = split_captions(narration) if captions else []
    bounds, run = [], 0
    for c in chunks:
        run += len(c.split())
        bounds.append(run)

    def caption_at(t):
        if not bounds:
            return 0
        seen = sum(1 for _w, s, _e in words if s <= t)
        return next((k for k, b in enumerate(bounds) if seen <= b), len(bounds) - 1)

    base = _static(g, kicker, handle)
    done, frames, last = [False] * len(items), [], None
    for k in range(max(1, int(round(length * fps)))):
        t = k / fps
        prog = timeline.progress(slots, t)
        key = (tuple(round(f, 2) for f in prog), caption_at(t))
        if key == last:
            frames[-1][1] += 1 / fps
            continue
        last = key
        for i, (it, f) in enumerate(zip(items, prog)):
            if f >= 1 and not done[i]:
                it.draw(lambda c: _mask(base, size, c), 1.0)
                done[i] = True
        masks, tip = {c: m.copy() for c, m in base.items()}, None
        for it, f in zip(items, prog):
            if 0 < f < 1:
                tip = it.draw(lambda c: _mask(masks, size, c), f) or tip
        png = Path(wd) / f"bb-{n:02d}-{len(frames):04d}.png"
        _compose(g, masks, tip, chunks[key[1]] if chunks else "").save(png, compress_level=1)
        frames.append([png, 1 / fps])
    return [(p, d) for p, d in frames], slots


def _segment(frames, length, out):
    lst = Path(out).with_suffix(".txt")
    lines = []
    for p, d in frames:
        lines += [f"file '{p}'", f"duration {d:.4f}"]
    lines.append(f"file '{frames[-1][0]}'")
    lst.write_text("\n".join(lines) + "\n")
    n = max(1, int(round(length * FPS)))
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps={FPS},format=yuv420p",
          "-frames:v", str(n), "-an"] + ENC + [str(out)], "Encoding a scene")


def timed(items):
    """The things in this scene that are drawn one after the other (all of them, for the blackboard)."""
    return items


def plan_groups(scenes):
    return [None] * len(scenes)


def render(scenes, out_path, fmt, workdir, audio=None, handle="", kicker="", captions=True, progress=None, redo=None, engine=None):
    """The whole video. `audio`: the voice, one file per scene (its lengths are the scenes' lengths), or one file, or None
    (then the scenes' own word counts set the pace). Returns the file's facts plus the timeline of every scene: when each thing
    was drawn and which words say it (the Video Editor checks that against the voice).
    redo: scene numbers (0-based) to draw again; the other scenes keep the pictures already drawn and are only joined again.
    The voice is never made here: it is the files the Voice step already recorded.
    engine: the module that draws (build, timed, plan_groups, render_scene): this one, or render/explainer.py."""
    eng = engine or sys.modules[__name__]
    if fmt not in FORMATS:
        raise VideoError(f"unknown format '{fmt}'")
    scenes = list(scenes or [])
    if not scenes:
        raise VideoError("no scenes to render")
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    cache = wd / "timeline.json"
    old = json.loads(cache.read_text()) if cache.exists() else {}
    lengths = _scene_lengths(scenes, audio)
    per_scene = audio if isinstance(audio, (list, tuple)) else [None] * len(scenes)
    groups = eng.plan_groups(scenes)
    segs, tl, at = [], [], 0.0
    for i, (sc, ln) in enumerate(zip(scenes, lengths)):
        seg = wd / f"seg-{i:02d}.mp4"
        kept = old.get(str(i))
        if redo is not None and i not in redo and seg.exists() and kept and abs(kept["seconds"] - ln) < 0.02:
            things, measured = kept["things"], kept["measured"]   # untouched scene: keep its picture
        else:
            frames, slots = eng.render_scene(sc, fmt, ln, wd, i, len(scenes), kicker, handle, captions, audio=per_scene[i], group=groups[i])
            _segment(frames, ln, seg)
            things = [{"cue": it.cue or "", "what": it.what, "start": round(s, 2), "end": round(e, 2)}
                      for it, (s, e) in zip(eng.timed(eng.build(sc, fmt, groups[i])), slots)]
            measured = timeline.voice_words(str(sc.get("narration", "")), ln, per_scene[i])[1]
        segs.append(seg)
        tl.append({"scene": i + 1, "start": round(at, 2), "seconds": round(ln, 2), "measured": measured, "things": things,
                   "drawn": [[round(at + t["start"], 2), round(at + t["end"], 2)] for t in things]})
        at += ln
        if progress:
            progress(i + 1, len(scenes))
    cache.write_text(json.dumps({str(i): {"seconds": e["seconds"], "things": e["things"], "measured": e["measured"]}
                                 for i, e in enumerate(tl)}))
    assemble(segs, lengths, audio, out_path)
    info = probe(out_path)
    return {"path": str(out_path), "seconds": info["seconds"], "width": info["width"], "height": info["height"], "timeline": tl}
