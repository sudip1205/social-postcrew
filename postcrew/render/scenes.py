"""Video frames: one PIL image per caption chunk, in the poster visual identity.

Layouts: title, statement, points, code, diagram (boxes and arrows that build up while the voice explains). Text is wrapped and shrunk to fit; it never overflows.
"""
import re

from PIL import Image

from .syntax import tokenize
from .theme import (BG, BORDER, CARD, CARD_HI, CODE_BG, CODE_BORDER, CREAM, GOLD, INK, MUTED, RULE, TEAL,
                    Painter, pill, text_width, wrap)

FORMATS = {"short": (1080, 1920), "long": (1920, 1080)}
MAX_CODE_LINES = 18


def split_captions(text, max_words=9):
    """Split narration into chunks of <= max_words words, preferring sentence then clause boundaries."""
    max_words = max(1, int(max_words))
    words = str(text or "").split()
    if not words:
        return []
    chunks, cur = [], []

    def flush():
        if cur:
            chunks.append(list(cur))
            del cur[:]

    for w in words:
        cur.append(w)
        end = w[-1]
        if end in ".!?" and len(cur) >= 2 or len(cur) >= max_words:
            flush()
        elif end in ",;:" and len(cur) >= max(3, max_words - 3):
            flush()
    flush()
    # merge a tiny trailing chunk into the previous one when it fits
    if len(chunks) > 1 and len(chunks[-1]) == 1 and len(chunks[-2]) < max_words:
        last = chunks.pop()
        chunks[-1] += last
    return [" ".join(c) for c in chunks]


def _fit(text, kind, max_w, max_h, start, lo, lh=1.25):
    """Largest size in [lo, start] whose wrapped text fits the box; truncates with an ellipsis as a last resort."""
    text = str(text or "").strip()
    size = start
    while True:
        lines = wrap(text, kind, size, max_w) if text else []
        if len(lines) * size * lh <= max_h or size <= lo:
            break
        size -= 2
    size = max(size, lo)
    cap = max(1, int(max_h // (size * lh)))
    if len(lines) > cap:
        lines = lines[:cap]
        last = lines[-1]
        while last and text_width(last + "…", kind, size) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines, size


def _draw_lines(p, x, y, lines, kind, size, fill, lh=1.25, anchor="la", mid=False):
    for i, ln in enumerate(lines):
        p.text((x, y + i * size * lh), ln, kind, size, fill, anchor=anchor)
    return y + len(lines) * size * lh


def _title(p, g, scene):
    x0, x1, top, bot = g["x0"], g["x1"], g["top"], g["bot"]
    items = [i for i in scene.get("items") or [] if str(i).strip()]
    sub_h = (bot - top) * 0.25 if items else 0
    lines, size = _fit(scene.get("on_screen") or "", "bold", x1 - x0, (bot - top) - sub_h, g["big"] * 1.3, 40, 1.15)
    sub, ssz = _fit(items[0], "sans", x1 - x0, sub_h, g["body"], 22, 1.3) if items else ([], 0)
    th = len(lines) * size * 1.15
    total = th + (len(sub) * ssz * 1.3 + 30 if sub else 0)
    y = top + max(0, (bot - top - total) / 2)
    p.rrect((x0, y - 28, x0 + 120, y - 20), r=4, fill=GOLD)
    y = _draw_lines(p, x0, y, lines, "bold", size, CREAM, 1.15)
    if sub:
        _draw_lines(p, x0, y + 30, sub, "sans", ssz, MUTED, 1.3)


def _statement(p, g, scene):
    x0, x1, top, bot = g["x0"], g["x1"], g["top"], g["bot"]
    text = scene.get("on_screen") or (scene.get("items") or [""])[0]
    lines, size = _fit(text, "bold", x1 - x0 - 40, bot - top, g["big"], 36, 1.22)
    h = len(lines) * size * 1.22
    y = top + max(0, (bot - top - h) / 2)
    p.rrect((x0, y, x0 + 10, y + h), r=5, fill=TEAL)
    _draw_lines(p, x0 + 40, y, lines, "bold", size, CREAM, 1.22)


def _points(p, g, scene):
    x0, x1, top, bot = g["x0"], g["x1"], g["top"], g["bot"]
    items = [str(i) for i in (scene.get("items") or []) if str(i).strip()][:5]
    head = scene.get("on_screen") or ""
    y = top
    if head:
        hl, hs = _fit(head, "bold", x1 - x0, (bot - top) * 0.2, g["body"] * 1.3, 28, 1.2)
        y = _draw_lines(p, x0, y, hl, "bold", hs, GOLD, 1.2) + 24
    if not items:
        return
    gap = 18
    row_h = (bot - y - gap * (len(items) - 1)) / len(items)
    row_h = min(row_h, g["body"] * 3.4)
    for n, it in enumerate(items, 1):
        r0 = y + (n - 1) * (row_h + gap)
        p.rrect((x0, r0, x1, r0 + row_h), r=18, fill=CARD, outline=BORDER, width=2)
        d = min(row_h - 24, 72)
        p.ellipse((x0 + 20, r0 + (row_h - d) / 2, x0 + 20 + d, r0 + (row_h + d) / 2), fill=GOLD)
        p.text((x0 + 20 + d / 2, r0 + row_h / 2), str(n), "bold", max(14, int(d * 0.5)), INK, anchor="mm")
        tx = x0 + 20 + d + 24
        lines, size = _fit(it, "semi", x1 - tx - 24, row_h - 20, g["body"], 18, 1.2)
        h = len(lines) * size * 1.2
        _draw_lines(p, tx, r0 + (row_h - h) / 2, lines, "semi", size, CREAM, 1.2)


def _code(p, g, scene):
    x0, x1, top, bot = g["x0"], g["x1"], g["top"], g["bot"]
    raw = str(scene.get("code") or "").replace("\t", "    ").rstrip().split("\n")
    lines = raw[:MAX_CODE_LINES]
    if len(raw) > MAX_CODE_LINES:
        lines[-1] = "..."
    lang = str(scene.get("language") or "").lower() or "code"
    y = top
    head = scene.get("on_screen") or ""
    if head:
        hl, hs = _fit(head, "bold", x1 - x0, (bot - top) * 0.14, g["body"] * 1.2, 24, 1.2)
        y = _draw_lines(p, x0, y, hl, "bold", hs, GOLD, 1.2) + 16
    pad = 26
    avail_h = bot - y - 2 * pad - 54
    avail_w = x1 - x0 - 2 * pad
    size = int(min(g["body"] * 0.6, avail_h / (max(1, len(lines)) * 1.4)))
    size = max(size, 10)
    while size > 10 and max([text_width(l, "mono", size) for l in lines] + [0]) > avail_w:
        size -= 1
    lh = size * 1.4
    box_h = min(bot - y, len(lines) * lh + 2 * pad + 54)
    p.rrect((x0, y, x1, y + box_h), r=22, fill=CODE_BG, outline=CODE_BORDER, width=2)
    p.text((x0 + pad, y + 16), lang, "mono", max(14, int(size * 0.7)), MUTED, tracking=1.5)
    cy = y + 40 + pad / 2 + 14
    for ln in lines:
        cx = x0 + pad
        for txt, col in tokenize(ln, lang):
            if cx + text_width(txt, "mono", size) > x1 - pad:  # clip rather than overflow
                while txt and cx + text_width(txt + "…", "mono", size) > x1 - pad:
                    txt = txt[:-1]
                txt += "…"
            p.text((cx, cy), txt, "mono", size, col)
            cx += text_width(txt, "mono", size)
            if cx >= x1 - pad:
                break
        cy += lh


def parse_edge(edge, nodes):
    """'Client > Load Balancer: request' -> (from index, to index, label), or None when it names a box that is not there."""
    m = re.match(r"^\s*(.+?)\s*(?:>|->|→)\s*(.+?)\s*(?::\s*(.*))?$", str(edge or ""))
    if not m:
        return None
    low = [n.lower() for n in nodes]
    a, b = m.group(1).lower(), m.group(2).lower()
    if a not in low or b not in low or a == b:
        return None
    return low.index(a), low.index(b), (m.group(3) or "").strip()[:24]


def _levels(n, edges):
    """Depth of every box counted from the first one along the arrows (a reply that goes back does not change it)."""
    level = {0: 0}
    for _ in range(n):
        for i, j, _l in edges:
            if i in level and j not in level:
                level[j] = level[i] + 1
    for i in range(n):   # boxes no arrow reaches go under the previous one
        level.setdefault(i, level.get(i - 1, 0) + 1 if i else 0)
    rows = {}
    for i in range(n):
        rows.setdefault(level[i], []).append(i)
    return [rows[k] for k in sorted(rows)]


def _exit_point(box, toward):
    """Where the line from the centre of `box` to the point `toward` leaves the box."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if not dx and not dy:
        return cx, cy
    s = min(((box[2] - box[0]) / 2) / abs(dx) if dx else 1e9, ((box[3] - box[1]) / 2) / abs(dy) if dy else 1e9)
    return cx + dx * s, cy + dy * s


def place_diagram(g, edges, count, y):
    """Where the boxes of a diagram go: ({index: (l, t, r, b)}, boxes by depth, vertical?). `y` is where the heading ends."""
    x0, x1, top, bot = g["x0"], g["x1"], g["top"], g["bot"]
    rows, vertical = _levels(count, edges), (x1 - x0) < (bot - top)
    boxes = {}
    n_lv = len(rows)
    if vertical:   # depth runs down the screen; boxes of one depth sit side by side
        bh = max(54, min(120, (bot - y) / (n_lv * 2.0)))
        gap_y = (bot - y - n_lv * bh) / max(1, n_lv - 1) if n_lv > 1 else 0
        for lv, row in enumerate(rows):
            k = len(row)
            gap = 36
            bw = min(480, (x1 - x0 - gap * (k - 1)) / k)
            left = x0 + (x1 - x0 - (bw * k + gap * (k - 1))) / 2
            t = y + lv * (bh + gap_y) if n_lv > 1 else y + (bot - y - bh) / 2
            for c, i in enumerate(row):
                boxes[i] = (left + c * (bw + gap), t, left + c * (bw + gap) + bw, t + bh)
    else:          # depth runs left to right; boxes of one depth are stacked
        bw = min(300, (x1 - x0) / (n_lv + 0.8 * max(1, n_lv - 1)))
        gap_x = min(460, (x1 - x0 - bw * n_lv) / max(1, n_lv - 1)) if n_lv > 1 else 0
        left = x0 + (x1 - x0 - (bw * n_lv + gap_x * (n_lv - 1))) / 2
        for lv, row in enumerate(rows):
            k = len(row)
            gap = 26
            bh = min(130, (bot - y - gap * (k - 1)) / k)
            t0 = y + (bot - y - (bh * k + gap * (k - 1))) / 2
            for c, i in enumerate(row):
                boxes[i] = (left + lv * (bw + gap_x), t0 + c * (bh + gap), left + lv * (bw + gap_x) + bw, t0 + c * (bh + gap) + bh)
    return boxes, rows, vertical


def _diagram(p, g, scene):
    """Up to 6 boxes placed by depth (the first box at the top / left, what it talks to below / to the right) and arrows between
    them. The arrows appear one by one as scene["_reveal"] goes from 0 to 1, so the picture builds up while the voice explains."""
    nodes = [str(n).strip()[:18] for n in (scene.get("nodes") or []) if str(n).strip()][:6]
    if len(nodes) < 2:
        return _statement(p, g, scene)
    edges = [e for e in (parse_edge(x, nodes) for x in (scene.get("edges") or [])) if e][:8]
    reveal = scene.get("_reveal", 1.0)
    shown = len(edges) if reveal >= 1 else (int(len(edges) * reveal + 0.999) if reveal > 0 else 0)
    x0, x1, top, bot = g["x0"], g["x1"], g["top"], g["bot"]
    y = top
    head = scene.get("on_screen") or ""
    if head:
        hl, hs = _fit(head, "bold", x1 - x0, (bot - top) * 0.14, g["body"] * 1.25, 26, 1.2)
        y = _draw_lines(p, x0, y, hl, "bold", hs, GOLD, 1.2) + 22
    boxes, rows, vertical = place_diagram(g, edges, len(nodes), y)
    small = g["body"] * 0.7
    touched = {i for e in edges[:shown] for i in e[:2]}
    for i, (l, t, r, b) in boxes.items():
        on = i in touched
        p.rrect((l, t, r, b), r=16, fill=CARD_HI if on else CARD, outline=TEAL if on else BORDER, width=3)
        lines, size = _fit(nodes[i], "bold", r - l - 24, b - t - 16, g["body"], 14, 1.15)
        h = len(lines) * size * 1.15
        _draw_lines(p, (l + r) / 2, t + (b - t - h) / 2, lines, "bold", size, CREAM, 1.15, anchor="ma")
    pairs = {(i, j) for i, j, _l in edges}
    lvl = {i: lv for lv, row in enumerate(rows) for i in row}
    bypass = 0
    for k, (i, j, label) in enumerate(edges[:shown]):
        colour = GOLD if k == shown - 1 else TEAL
        a, b = boxes[i], boxes[j]
        if abs(lvl[i] - lvl[j]) > 1:   # a hop over other boxes goes round the outside instead of through them
            bypass += 1
            if vertical:
                xr = x1 + 14 + 26 * bypass
                ya, yb = (a[1] + a[3]) / 2, (b[1] + b[3]) / 2
                p.line((a[2], ya), (xr, ya), fill=colour, width=5)
                p.line((xr, ya), (xr, yb), fill=colour, width=5)
                p.arrow((xr, yb), (b[2], yb), fill=colour, width=5, head=18)
                mid, anchor = (xr - 10, (ya + yb) / 2), "rm"
            else:
                def blocked(box, up):   # another box in the same column between this one and the edge of the picture
                    return any(o is not box and o[0] < box[2] and o[2] > box[0] and (o[3] <= box[1] if up else o[1] >= box[3])
                               for o in boxes.values())
                over = not (blocked(a, True) or blocked(b, True)) or (blocked(a, False) or blocked(b, False))
                xa, xb = (a[0] + a[2]) / 2, (b[0] + b[2]) / 2
                if over:
                    yt = max(y + 8, min(bx[1] for bx in boxes.values()) - 34 - 30 * bypass)
                    ya, yb = a[1], b[1]
                else:
                    yt = min(bot - 8, max(bx[3] for bx in boxes.values()) + 34 + 30 * bypass)
                    ya, yb = a[3], b[3]
                p.line((xa, ya), (xa, yt), fill=colour, width=5)
                p.line((xa, yt), (xb, yt), fill=colour, width=5)
                p.arrow((xb, yt), (xb, yb), fill=colour, width=5, head=18)
                mid, anchor = ((xa + xb) / 2, yt - 6 if over else yt + 22), "ms"
            if label:
                w = text_width(label, "semi", small) + 20
                lx = mid[0] - w if anchor == "rm" else mid[0] - w / 2
                p.rrect((lx, mid[1] - small * 0.8, lx + w, mid[1] + small * 0.8), r=8, fill=BG)
                p.text((lx + w / 2, mid[1]), label, "semi", small, colour, anchor="mm")
            continue
        ca, cb = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        dx, dy = cb[0] - ca[0], cb[1] - ca[1]
        norm = (dx * dx + dy * dy) ** 0.5 or 1
        off = 16 if (j, i) in pairs else 0           # an answer going back runs beside the request, not over it
        ox, oy = -dy / norm * off, dx / norm * off
        p0 = _exit_point(a, (cb[0] + ox, cb[1] + oy))
        p1 = _exit_point(b, (ca[0] + ox, ca[1] + oy))
        p0, p1 = (p0[0] + ox, p0[1] + oy), (p1[0] + ox, p1[1] + oy)
        p.arrow(p0, p1, fill=colour, width=5, head=18)
        if label:
            mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
            side = 1 if off >= 0 else -1
            lx, ly = mx + (-dy / norm) * (30 * side if off else 0), my + (dx / norm) * (30 * side if off else 0)
            w = text_width(label, "semi", small) + 20
            if not off:
                lx, ly = mx + 14, my   # beside a straight arrow
                p.rrect((lx - 6, ly - small * 0.8, lx + w, ly + small * 0.8), r=8, fill=BG)
                p.text((lx + 4, ly), label, "semi", small, colour, anchor="lm")
            else:
                p.rrect((lx - w / 2, ly - small * 0.8, lx + w / 2, ly + small * 0.8), r=8, fill=BG)
                p.text((lx, ly), label, "semi", small, colour, anchor="mm")


LAYOUTS = {"title": _title, "statement": _statement, "points": _points, "code": _code, "diagram": _diagram}


def draw_frame(scene, fmt, caption="", kicker="", handle="", index=0, total=1, reveal=1.0):
    """reveal: 0-1, how much of a diagram scene is drawn yet (its arrows appear one by one as the voice explains)."""
    w, h = FORMATS.get(fmt, FORMATS["short"])
    short = h > w
    scene = dict(scene or {}, _reveal=reveal)
    p = Painter(w, h, 2)
    m = 72 if short else 110
    u = w if short else h  # scale unit
    g = {"x0": m, "x1": w - m, "big": u * (0.085 if short else 0.11), "body": u * (0.04 if short else 0.052)}
    # progress bar
    frac = min(1.0, max(0.0, (index + 1) / max(1, total)))
    p.rrect((0, 0, w, 10), r=0, fill=RULE)
    p.rrect((0, 0, max(6, w * frac), 10), r=0, fill=TEAL)
    # kicker
    ky = 70 if short else 44
    label = str(kicker or "").upper()[:40]
    if label:
        pill(p, (m, ky), label, size=22 if short else 20, height=46 if short else 42)
    # caption box (short: bottom edge 17% above the bottom = inside the safe area)
    cap_bot = h * (0.83 if short else 0.90)
    cap_h = h * (0.14 if short else 0.19)
    cap_top = cap_bot - cap_h
    g["top"] = ky + 46 + (50 if short else 36)
    g["bot"] = cap_top - (40 if short else 30)
    LAYOUTS.get(scene.get("layout"), _statement)(p, g, scene)
    cap = str(caption or "").strip()
    if cap:
        cl, cs = _fit(cap, "semi", w - 2 * m - 60, cap_h - 36, u * (0.042 if short else 0.052), 20, 1.25)
        ch = len(cl) * cs * 1.25
        bh = ch + 36
        top = cap_bot - bh
        p.rrect((m, top, w - m, cap_bot), r=22, fill=CARD_HI, outline=TEAL, width=2)
        _draw_lines(p, w / 2, top + 18, cl, "semi", cs, CREAM, 1.25, anchor="ma")
    hd = str(handle or "")
    if hd:
        size = 24 if short else 22
        while text_width(hd, "bold", size) > w - 2 * m and size > 12:
            size -= 1
        p.text((w - m, h - (60 if short else 36)), hd, "bold", size, MUTED, anchor="rm")
    return p.result()
