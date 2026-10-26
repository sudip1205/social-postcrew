"""Shared look for posters and animations (matches the existing media/ style).

Everything is drawn through Painter, which works in 1x coordinates but renders at
2x and downsamples, so edges are anti-aliased.
"""
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
FONT_DIR = Path(__file__).parent / "fonts"

BG = "#0c2035"
PANEL = "#14304d"
CARD = "#17314f"
CARD_HI = "#1f4066"
BORDER = "#2b4a73"
CREAM = "#f4efe6"
MUTED = "#9fb0c8"
TEAL = "#3bd4c5"
GOLD = "#efb749"
CORAL = "#f07a66"
BAR = "#597ea4"
BAR_DIM = "#3a5878"
CODE_BG = "#091727"
CODE_BORDER = "#1f3f66"
HL_LINE = "#26507c"
RULE = "#345275"
INK = "#0c2035"  # dark text on gold/teal fills

# Inter / JetBrains Mono lack these; DejaVu draws them instead.
FALLBACK_CHARS = set("∞→←✓≤≥≈")
_FILES = {
    "sans": "Inter-Regular.ttf", "semi": "Inter-SemiBold.ttf", "bold": "Inter-Bold.ttf",
    "mono": "JetBrainsMono-Regular.ttf", "monob": "JetBrainsMono-Bold.ttf",
}
_FALLBACK = {
    "sans": "DejaVuSans.ttf", "semi": "DejaVuSans-Bold.ttf", "bold": "DejaVuSans-Bold.ttf",
    "mono": "DejaVuSansMono.ttf", "monob": "DejaVuSansMono-Bold.ttf",
}


@lru_cache(maxsize=None)
def font(kind, size, fallback=False):
    name = (_FALLBACK if fallback else _FILES)[kind]
    return ImageFont.truetype(str(FONT_DIR / name), int(round(size)))


def _runs(s):
    """Split s into (text, use_fallback) runs."""
    out, cur, cur_fb = [], "", False
    for ch in s:
        fb = ch in FALLBACK_CHARS
        if cur and fb != cur_fb:
            out.append((cur, cur_fb))
            cur = ""
        cur, cur_fb = cur + ch, fb
    if cur:
        out.append((cur, cur_fb))
    return out


def text_width(s, kind, size, tracking=0.0):
    """Width in 1x units of s drawn at `size` px."""
    if tracking:
        return sum(font(kind, size, ch in FALLBACK_CHARS).getlength(ch) + tracking for ch in s) - tracking
    return sum(font(kind, size, fb).getlength(t) for t, fb in _runs(s))


def wrap(s, kind, size, max_w):
    """Greedy word wrap. Honors explicit newlines. Over-long words are hard-split."""
    lines = []
    for para in str(s).split("\n"):
        cur = ""
        for word in para.split(" "):
            while text_width(word, kind, size) > max_w and len(word) > 1:  # hard split
                k = len(word)
                while k > 1 and text_width(word[:k], kind, size) > max_w:
                    k -= 1
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:k])
                word = word[k:]
            trial = f"{cur} {word}".strip() if cur else word
            if text_width(trial, kind, size) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


class Painter:
    def __init__(self, w, h, scale=2, bg=BG):
        self.w, self.h, self.s = w, h, scale
        self.img = Image.new("RGB", (w * scale, h * scale), bg)
        self.d = ImageDraw.Draw(self.img)

    def _sc(self, v):
        return v * self.s

    def rrect(self, box, r=16, fill=None, outline=None, width=2):
        x0, y0, x1, y1 = (self._sc(v) for v in box)
        self.d.rounded_rectangle((x0, y0, x1, y1), radius=self._sc(r), fill=fill, outline=outline,
                                 width=max(1, int(round(self._sc(width)))) if outline else 0)

    def ellipse(self, box, fill=None, outline=None, width=2):
        self.d.ellipse([self._sc(v) for v in box], fill=fill, outline=outline,
                       width=max(1, int(round(self._sc(width)))) if outline else 0)

    def line(self, p0, p1, fill, width=2):
        self.d.line([self._sc(p0[0]), self._sc(p0[1]), self._sc(p1[0]), self._sc(p1[1])],
                    fill=fill, width=max(1, int(round(self._sc(width)))))

    def dashed_rrect(self, box, r=16, fill=None, outline=BORDER, width=2, dash=10, gap=8):
        x0, y0, x1, y1 = box
        if fill:
            self.rrect(box, r, fill=fill)
        for (a, b, c, d_) in ((x0 + r, y0, x1 - r, y0), (x0 + r, y1, x1 - r, y1),
                              (x0, y0 + r, x0, y1 - r), (x1, y0 + r, x1, y1 - r)):
            horiz = a != c
            pos, end = (a, c) if horiz else (b, d_)
            while pos < end:
                nxt = min(pos + dash, end)
                if horiz:
                    self.line((pos, b), (nxt, b), outline, width)
                else:
                    self.line((a, pos), (a, nxt), outline, width)
                pos = nxt + gap

    def polygon(self, pts, fill):
        self.d.polygon([(self._sc(x), self._sc(y)) for x, y in pts], fill=fill)

    def arrow(self, p0, p1, fill=TEAL, width=3, head=12):
        """Line from p0 to p1 with a triangular head at p1."""
        import math
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        n = math.hypot(dx, dy) or 1
        ux, uy = dx / n, dy / n
        base = (p1[0] - ux * head, p1[1] - uy * head)
        self.line(p0, base, fill, width)
        px, py = -uy, ux
        self.polygon([p1, (base[0] + px * head * 0.6, base[1] + py * head * 0.6),
                      (base[0] - px * head * 0.6, base[1] - py * head * 0.6)], fill)

    def ascent(self, kind, size):
        """Ascent of a font in 1x units (to align baselines of different sizes)."""
        return font(kind, self._sc(size)).getmetrics()[0] / self.s

    def text(self, xy, s, kind="sans", size=24, fill=CREAM, anchor="la", tracking=0.0):
        """Draw s. anchor = horizontal (l/m/r) + vertical (a=top, m=middle, s=baseline)."""
        x, y = xy
        s = str(s)
        sz = self._sc(size)
        main = font(kind, sz)
        asc, desc = main.getmetrics()
        h, v = anchor[0], anchor[1]
        w = text_width(s, kind, sz, tracking * self.s)
        x0 = self._sc(x) - (w if h == "r" else w / 2 if h == "m" else 0)
        base = self._sc(y) + {"a": asc, "m": (asc - desc) / 2, "s": 0}[v]
        if tracking:
            for ch in s:
                f = font(kind, sz, ch in FALLBACK_CHARS)
                self.d.text((x0, base), ch, font=f, fill=fill, anchor="ls")
                x0 += f.getlength(ch) + tracking * self.s
            return
        for t, fb in _runs(s):
            f = font(kind, sz, fb)
            self.d.text((x0, base), t, font=f, fill=fill, anchor="ls")
            x0 += f.getlength(t)

    def result(self):
        if self.s == 1:
            return self.img
        return self.img.resize((self.w, self.h), Image.LANCZOS)


def pill(p, xy, label, fill=GOLD, ink=INK, size=22, pad_x=28, height=48):
    """Rounded kicker pill (e.g. 'MODEL LAUNCH'). Returns its right edge."""
    x, y = xy
    w = text_width(label, "bold", size, tracking=2.4) + 2 * pad_x
    p.rrect((x, y, x + w, y + height), r=height / 2, fill=fill)
    p.text((x + pad_x, y + height / 2), label, "bold", size, ink, anchor="lm", tracking=2.4)
    return x + w


def footer(p, left, right, y_rule=1255, size=24):
    p.line((60, y_rule), (1020, y_rule), RULE, 2)
    while text_width(left, "sans", size) + text_width(right, "bold", size) > 900 and size > 16:
        size -= 1  # never let the two sides touch
    p.text((60, y_rule + 36), left, "sans", size, MUTED, anchor="lm")
    p.text((1020, y_rule + 36), right, "bold", size, CREAM, anchor="rm")
