"""Render a LinkedIn poster (1080x1350 PNG) from a small JSON spec.

Layouts: points (cards), steps (numbered timeline), code (code panel), flow (boxes + arrows).
Raises PosterError when the text cannot fit, so the caller can ask for shorter copy.
"""
import re
from pathlib import Path

from .syntax import tokenize
from .theme import (BG, BORDER, CARD, CARD_HI, CODE_BG, CODE_BORDER, CREAM, GOLD, H, INK, MUTED,
                    TEAL, W, Painter, footer, pill, text_width, wrap)

LAYOUTS = ("points", "steps", "code", "flow")
LIMITS = {"kicker": 26, "title": 90, "subtitle": 170, "footer_left": 70}
BODY_BOTTOM = 1225
SCALES = (1.4, 1.3, 1.2, 1.1, 1.0, 0.92, 0.85, 0.78, 0.7)


class PosterError(ValueError):
    pass


# ---------- rich title: [[accent]] words are drawn in teal ----------
def _rich_words(s):
    words = []
    for part in re.split(r"(\[\[.*?\]\])", s):
        accent = part.startswith("[[") and part.endswith("]]")
        for w in (part[2:-2] if accent else part).split():
            words.append((w, TEAL if accent else CREAM))
    return words


def _rich_wrap(s, size, max_w):
    lines, cur, cur_w = [], [], 0
    space = text_width(" ", "bold", size)
    for w, color in _rich_words(s):
        ww = text_width(w, "bold", size)
        if cur and cur_w + space + ww > max_w:
            lines.append(cur)
            cur, cur_w = [], 0
        cur_w += (space if cur else 0) + ww
        cur.append((w, color))
    if cur:
        lines.append(cur)
    return lines


def _check_len(spec, key, required=False):
    v = spec.get(key, "")
    if required and not v:
        raise PosterError(f"poster needs '{key}'")
    if len(v) > LIMITS[key]:
        raise PosterError(f"poster '{key}' is {len(v)} chars; the limit is {LIMITS[key]}")


def _header(p, spec):
    """Draw pill, title, subtitle. Returns the y where the body can start."""
    for k in ("kicker", "title"):
        _check_len(spec, k, required=True)
    _check_len(spec, "subtitle")
    pill(p, (60, 64), spec["kicker"].upper())
    for size in (70, 64, 58, 52):
        lines = _rich_wrap(spec["title"], size, 960)
        if len(lines) <= 3:
            break
    else:
        raise PosterError("poster title needs more than 3 lines; shorten it")
    y, lh = 150, size * 1.14
    for ln in lines:
        x = 60
        for w, color in ln:
            p.text((x, y), w, "bold", size, color)
            x += text_width(w, "bold", size) + text_width(" ", "bold", size)
        y += lh
    y += 6
    sub = spec.get("subtitle", "")
    if sub:
        for size in (30, 28, 26):
            sl = wrap(sub, "sans", size, 960)
            if len(sl) <= 3:
                break
        else:
            raise PosterError("poster subtitle needs more than 3 lines; shorten it")
        for ln in sl:
            p.text((60, y), ln, "sans", size, MUTED)
            y += size * 1.38
        y += 4
    return y + 22


def _items(spec, lo, hi, keys):
    items = spec.get("items")
    if not isinstance(items, list) or not (lo <= len(items) <= hi):
        raise PosterError(f"'{spec.get('layout')}' layout needs {lo}-{hi} items")
    for it in items:
        if not isinstance(it, dict) or not it.get(keys[0]):
            raise PosterError(f"every item needs '{keys[0]}'")
    return items


def _fit(draw_fn, top, bottom):
    """draw_fn(painter, y, k) -> end y. Pick the largest scale k that fits."""
    err = None
    for k in SCALES:
        try:
            if draw_fn(Painter(W, 4000, scale=1), top, k) <= bottom - 40:  # keep some air above the footer
                return k
        except PosterError as e:  # e.g. a code line too wide at this size; try smaller
            err = e
    raise err or PosterError("poster content is too long to fit; use fewer or shorter items")


# ---------- layouts ----------
def _points(p, spec, top, k):
    items = _items(spec, 2, 5, ("head", "body"))
    y = top
    for i, it in enumerate(items):
        pad, badge = 26 * k, 52 * k
        tx = 60 + pad + badge + 22 * k
        tw = 1020 - pad - tx
        head = wrap(it["head"], "bold", 32 * k, tw)
        body = wrap(it.get("body", ""), "sans", 26 * k, tw) if it.get("body") else []
        h = 2 * pad + len(head) * 40 * k + (8 * k + len(body) * 34 * k if body else 0)
        h = max(h, 2 * pad + badge)
        accent = TEAL if i % 2 == 0 else GOLD
        p.rrect((60, y, 1020, y + h), r=20, fill=CARD, outline=BORDER if i else accent, width=2)
        cy = y + h / 2 if not body else y + pad + 26 * k
        p.ellipse((60 + pad, cy - badge / 2, 60 + pad + badge, cy + badge / 2), fill=accent)
        p.text((60 + pad + badge / 2, cy), str(i + 1), "bold", 26 * k, INK, anchor="mm")
        ty = y + pad
        for ln in head:
            p.text((tx, ty), ln, "bold", 32 * k, CREAM)
            ty += 40 * k
        if body:
            ty += 8 * k
            for ln in body:
                p.text((tx, ty), ln, "sans", 26 * k, MUTED)
                ty += 34 * k
        y += h + 18 * k
    return y - 18 * k


def _steps(p, spec, top, k):
    items = _items(spec, 3, 7, ("head", "body"))
    circ = 52 * k
    x_rail, tx = 60 + circ / 2, 60 + circ + 26 * k
    tw = 1020 - tx
    blocks, y = [], top
    for it in items:
        head = wrap(it["head"], "bold", 32 * k, tw)
        body = wrap(it.get("body", ""), "sans", 26 * k, tw) if it.get("body") else []
        h = max(circ, len(head) * 40 * k + (6 * k + len(body) * 34 * k if body else 0))
        blocks.append((y, h, head, body))
        y += h + 30 * k
    if len(blocks) > 1:
        p.line((x_rail, blocks[0][0] + circ / 2), (x_rail, blocks[-1][0] + circ / 2), BORDER, 3)
    for i, (by, h, head, body) in enumerate(blocks):
        p.ellipse((60, by, 60 + circ, by + circ), fill=TEAL if i < len(blocks) - 1 else GOLD)
        p.text((x_rail, by + circ / 2), str(i + 1), "bold", 26 * k, INK, anchor="mm")
        ty = by + (4 * k)
        for ln in head:
            p.text((tx, ty), ln, "bold", 32 * k, CREAM)
            ty += 40 * k
        if body:
            ty += 6 * k
            for ln in body:
                p.text((tx, ty), ln, "sans", 26 * k, MUTED)
                ty += 34 * k
    y -= 30 * k
    res = spec.get("result")
    if res:
        y += 26 * k
        lines = wrap(res, "semi", 28 * k, 960 - 56 * k)
        h = 2 * 22 * k + 26 * k + len(lines) * 36 * k
        p.rrect((60, y, 1020, y + h), r=18, fill=CARD_HI, outline=TEAL, width=2)
        p.text((60 + 28 * k, y + 22 * k), "RESULT", "bold", 18 * k, TEAL, tracking=2.4)
        ty = y + 22 * k + 28 * k
        for ln in lines:
            p.text((60 + 28 * k, ty), ln, "semi", 28 * k, CREAM)
            ty += 36 * k
        y += h
    return y


def _code(p, spec, top, k):
    code = spec.get("code", "").rstrip("\n").split("\n")
    lang = spec.get("language", "python").lower()
    if not (2 <= len(code) <= 16):
        raise PosterError("code layout needs 2-16 lines of code")
    size = 26 * k
    num_w = 44 * k
    inner = 960 - 2 * 26 * k - num_w
    longest = max(text_width(ln.replace("\t", "    "), "mono", size) for ln in code)
    if longest > inner:
        raise PosterError("a code line is too wide; keep lines under ~55 characters")
    lh = size * 1.42
    h = 26 * k + 30 * k + len(code) * lh + 26 * k
    p.rrect((60, top, 1020, top + h), r=20, fill=CODE_BG, outline=CODE_BORDER, width=2)
    p.text((60 + 26 * k, top + 20 * k), lang.capitalize(), "mono", 20 * k, MUTED, tracking=1.5)
    y = top + 26 * k + 30 * k
    for i, ln in enumerate(code, 1):
        p.text((60 + 26 * k + num_w - 14 * k, y + p.ascent("mono", size)), str(i), "mono", size * 0.82,
               "#4d6a8c", anchor="rs")
        x = 60 + 26 * k + num_w
        for txt, color in tokenize(ln.replace("\t", "    "), lang):
            p.text((x, y), txt, "mono", size, color)
            x += text_width(txt, "mono", size)
        y += lh
    y = top + h
    cap = spec.get("caption")
    if cap:
        y += 22 * k
        lines = wrap(cap, "semi", 28 * k, 960 - 56 * k)
        ch = 2 * 20 * k + len(lines) * 36 * k
        p.rrect((60, y, 1020, y + ch), r=18, fill=CARD_HI, outline=TEAL, width=2)
        ty = y + 20 * k
        for ln in lines:
            p.text((60 + 28 * k, ty), ln, "semi", 28 * k, CREAM)
            ty += 36 * k
        y += ch
    for b in spec.get("bullets", [])[:3]:
        y += 16 * k
        for j, ln in enumerate(wrap(b, "sans", 26 * k, 920 - 30 * k)):
            if j == 0:
                p.ellipse((72, y + 12 * k, 72 + 10 * k, y + 22 * k), fill=GOLD)
            p.text((100 + 0 * k, y), ln, "sans", 26 * k, MUTED)
            y += 34 * k
    return y


def _flow(p, spec, top, k):
    items = _items(spec, 2, 6, ("label", "sub"))
    hi = spec.get("highlight")
    y = top
    for i, it in enumerate(items):
        pad = 22 * k
        tag = it.get("tag", "")
        tag_w = (text_width(tag.upper(), "bold", 18 * k, 1.5 * k) + 28 * k) if tag else 0
        tw = 960 - 2 * pad - tag_w - (12 * k if tag else 0)
        label = wrap(it["label"], "bold", 32 * k, tw)
        sub = wrap(it.get("sub", ""), "sans", 25 * k, 960 - 2 * pad) if it.get("sub") else []
        h = 2 * pad + len(label) * 40 * k + (6 * k + len(sub) * 33 * k if sub else 0)
        on = hi == i
        p.rrect((60, y, 1020, y + h), r=18, fill=CARD_HI if on else CARD, outline=GOLD if on else TEAL if i == 0 else BORDER,
                width=3 if on else 2)
        ty = y + pad
        for ln in label:
            p.text((60 + pad, ty), ln, "bold", 32 * k, CREAM)
            ty += 40 * k
        if sub:
            ty += 6 * k
            for ln in sub:
                p.text((60 + pad, ty), ln, "sans", 25 * k, MUTED)
                ty += 33 * k
        if tag:
            x1 = 1020 - pad
            p.rrect((x1 - tag_w, y + pad, x1, y + pad + 36 * k), r=18 * k, outline=TEAL, width=2)
            p.text((x1 - tag_w / 2, y + pad + 18 * k), tag.upper(), "bold", 18 * k, TEAL, anchor="mm", tracking=1.5 * k)
        y += h
        if i < len(items) - 1:
            via = it.get("via", "")
            p.arrow((540, y + 4), (540, y + 44 * k), TEAL, 3, 12 * k)
            if via:
                p.text((560, y + 22 * k), via, "sans", 22 * k, MUTED, anchor="lm")
            y += 48 * k
    return y


_LAYOUT_FN = {"points": _points, "steps": _steps, "code": _code, "flow": _flow}


def render_poster(spec, out_path, handle=""):
    layout = spec.get("layout")
    if layout not in _LAYOUT_FN:
        raise PosterError(f"unknown poster layout '{layout}' (use one of {', '.join(LAYOUTS)})")
    _check_len(spec, "footer_left")
    # measure the header on a throwaway painter to learn where the body starts
    probe = Painter(W, H, scale=1)
    body_top = _header(probe, spec)
    fn = _LAYOUT_FN[layout]
    k = _fit(lambda pp, y, kk: fn(pp, spec, y, kk), body_top, BODY_BOTTOM)
    p = Painter(W, H, scale=2)
    _header(p, spec)
    fn(p, spec, body_top, k)
    footer(p, spec.get("footer_left", ""), handle)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    p.result().save(out, optimize=True)
    return out


def poster_text(spec):
    """All text shown on the poster, for the gate and the judge."""
    parts = [spec.get(k, "") for k in ("kicker", "title", "subtitle", "caption", "result", "footer_left")]
    for it in spec.get("items", []):
        parts += [it.get(k, "") for k in ("head", "body", "label", "sub", "tag", "via")]
    parts += spec.get("bullets", [])
    if spec.get("code"):
        parts.append(spec["code"])
    return "\n".join(x for x in parts if x).replace("[[", "").replace("]]", "")
