"""Render a Tracer to an MP4 (1080x1350, H.264, 30 fps) in the same style as the earlier videos.

Pillow draws the frames, ffmpeg encodes them. Static layers are cached; a hold longer than one
frame reuses the same bytes, so only moving frames cost real rendering time.
"""
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from .syntax import tokenize
from .theme import (BAR, BAR_DIM, BG, BORDER, CARD, CARD_HI, CODE_BG, CODE_BORDER, CORAL, CREAM, GOLD, H,
                    HL_LINE, INK, MUTED, TEAL, W, Painter, footer, pill, text_width)
from .tracers import TRACERS

FPS = 30
TWEEN_S = 0.45
MAX_SECONDS = 45.0
VIZ_Y, VIZ_H = 240, 462
CAP_BOX = (60, 708, 1020, 766)
CODE_BOX = (60, 786, 1020, 1236)
ROWS, ROW_H = 14, 28.5

ROLE_FILL = {"bar": BAR, "dim": BAR_DIM, "pivot": GOLD, "mid": GOLD, "cmp": "#9cc4ec", "swap": CORAL,
             "sorted": TEAL}
PTR_COLOR = {"pivot": GOLD, "mid": GOLD, "found": TEAL, "done": TEAL, "i": TEAL, "j": CORAL, "k": MUTED,
             "lo": TEAL, "hi": CORAL, "key": GOLD}
EDGE = "#35567f"


class AnimationError(RuntimeError):
    pass


# ---------- cached layers ----------
def _base(t, handle):
    p = Painter(W, H, 2)
    pill(p, (60, 52), "ALGORITHM IN JAVA", size=20, height=44)
    p.text((60, 112), t.title, "bold", 58, CREAM)
    p.text((60, 188), t.subtitle, "sans", 26, MUTED)
    footer(p, t.complexity, handle, y_rule=1257)
    return p.result()


def _caption_img(text):
    p = Painter(960, 58, 2, bg=BG)
    p.rrect((1, 1, 959, 57), r=16, fill=CARD_HI, outline=TEAL, width=2)
    size = 26
    while text_width(text, "semi", size) > 912 and size > 18:
        size -= 1
    p.text((24, 29), text, "semi", size, CREAM, anchor="lm")
    return p.result()


def _window_start(prev, hl, n):
    if n <= ROWS:
        return 0
    if hl is None:
        return prev
    if prev + 1 <= hl <= prev + ROWS - 2:
        return prev
    return max(0, min(hl - 5, n - ROWS))


def check_code_fits(lines):
    """Raise if a Java line would run past the code panel instead of silently clipping it."""
    for n, ln in enumerate(lines, 1):
        if text_width(ln, "mono", 22) > 868:
            raise AnimationError(f"Java line {n} is too wide for the video; wrap it: {ln.strip()[:50]}")


def _code_img(lines, hl, start):
    p = Painter(960, 450, 2, bg=BG)
    p.rrect((1, 1, 959, 449), r=22, fill=CODE_BG, outline=CODE_BORDER, width=2)
    p.text((24, 17), "Java", "mono", 17, MUTED, tracking=1.5)
    for k, idx in enumerate(range(start, min(start + ROWS, len(lines)))):
        y = 36 + k * ROW_H
        if hl == idx + 1:
            p.rrect((8, y - 1, 952, y + ROW_H - 1.5), r=4, fill=HL_LINE)
            p.rrect((8, y - 1, 13, y + ROW_H - 1.5), r=2, fill=GOLD)
        p.text((52, y + p.ascent("mono", 22) - 3), str(idx + 1), "mono", 19, MUTED if hl != idx + 1 else CREAM,
               anchor="rs")
        x = 68
        for txt, color in tokenize(lines[idx], "java"):
            p.text((x, y), txt, "mono", 22, color)
            x += text_width(txt, "mono", 22)
    return p.result()


# ---------- viz: bars ----------
def _ease(t):
    return t * t * (3 - 2 * t)


def _draw_bars(p, v, prev, t):
    order, val, roles = v["order"], v["val"], v["roles"]
    n = len(order)
    gap = 18 if n <= 10 else 14
    bw = min(90, (960 - gap * (n - 1)) / n)
    x0 = 60 + (960 - (n * bw + (n - 1) * gap)) / 2
    has_aux = v["aux"] is not None
    base, hmax = (290, 190) if has_aux else (360, 255)
    maxv = max(val.values())

    def x_of(pos):
        return x0 + pos * (bw + gap)

    rng = v["range"]
    if rng and rng[0] <= rng[1]:
        p.dashed_rrect((x_of(rng[0]) - 10, 12, x_of(rng[1]) + bw + 10, 436), r=18, fill="#0f2840", outline=BORDER)
        if v["range_label"]:
            p.text((x_of(rng[0]) - 1, 18), v["range_label"], "semi", 20, MUTED)
    for pos in range(n):
        p.text((x_of(pos) + bw / 2, base + 22), str(pos), "sans", 20, MUTED, anchor="mm")
    prev_pos = {i: pos for pos, i in enumerate(prev["order"])} if prev else {}
    for pos, i in enumerate(order):
        x = x_of(pos)
        if i in prev_pos and t < 1:
            x = x_of(prev_pos[i]) + (x - x_of(prev_pos[i])) * _ease(t)
        h = max(8, hmax * val[i] / maxv)
        role = roles.get(i, "bar")
        p.rrect((x, base - h, x + bw, base), r=8, fill=ROLE_FILL[role])
        p.text((x + bw / 2, base - h - 18), str(val[i]), "bold", 24, MUTED if role == "dim" else CREAM, anchor="mm")
    for pos, labels in v["pointers"].items():
        cx = x_of(pos) + bw / 2
        color = PTR_COLOR.get(labels[0], GOLD)
        p.polygon([(cx, base + 38), (cx - 9, base + 50), (cx + 9, base + 50)], color)
        p.text((cx, base + 66), "/".join(labels), "bold", 20, color, anchor="mm")
    if has_aux:
        p.text((60, 386), "tmp", "mono", 18, MUTED, anchor="lm")
        for pos, value in v["aux"]:
            x = x_of(pos)
            if value is None:
                p.dashed_rrect((x, 398, x + bw, 432), r=6, outline=BORDER, dash=6, gap=5)
            else:
                p.rrect((x, 398, x + bw, 432), r=6, fill=CARD_HI, outline=TEAL, width=2)
                p.text((x + bw / 2, 415), str(value), "bold", 22, CREAM, anchor="mm")


# ---------- viz: graph ----------
NODE_STYLE = {"unseen": (CARD_HI, "#2f5a8a", CREAM), "queued": (CARD_HI, TEAL, CREAM),
              "current": (GOLD, GOLD, INK), "done": (TEAL, TEAL, INK)}


def _draw_graph(p, v):
    pos = {n: (x, y - VIZ_Y) for n, (x, y) in v["pos"].items()}
    active = v["active_edge"]
    for a, b in v["edges"]:
        on = active and {a, b} == set(active)
        p.line(pos[a], pos[b], TEAL if on else EDGE, 7 if on else 4)
    for n, (x, y) in pos.items():
        fill, outline, ink = NODE_STYLE[v["roles"][n]]
        r = 38
        p.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=outline, width=4)
        p.text((x, y), n, "bold", 30, ink, anchor="mm")
        lab = v["labels"].get(n)
        if lab:
            p.text((x, y + r + 24), lab, "semi", 22, GOLD if v["roles"][n] == "current" else MUTED, anchor="mm")
    y = 420
    p.text((60, y), v["chips_label"], "bold", 24, MUTED, anchor="lm")
    x = 60 + text_width(v["chips_label"], "bold", 24) + 26
    if not v["chips"]:
        p.text((x, y), "(empty)", "sans", 24, MUTED, anchor="lm")
    for c in v["chips"]:
        p.rrect((x, y - 22, x + 52, y + 22), r=10, fill=CARD_HI, outline=TEAL, width=2)
        p.text((x + 26, y), c, "bold", 24, CREAM, anchor="mm")
        x += 64


def _viz_img(f, prev, t):
    p = Painter(W, VIZ_H, 2, bg=BG)
    v = f["viz"]
    if v["kind"] == "bars":
        _draw_bars(p, v, prev["viz"] if prev and prev["viz"]["kind"] == "bars" else None, t)
    else:
        _draw_graph(p, v)
    return p.result()


# ---------- timing ----------
def _scaled_durations(frames):
    """Squeeze long traces to MAX_SECONDS, keeping intro/outro (line None) intact."""
    total = sum(f["dur"] for f in frames)
    if total <= MAX_SECONDS:
        return [f["dur"] for f in frames]
    fixed = sum(f["dur"] for f in frames if f["line"] is None)
    k = (MAX_SECONDS - fixed) / (total - fixed)
    return [f["dur"] if f["line"] is None else max(0.4, f["dur"] * k) for f in frames]


def render_animation(tracer, out_path, handle="", fps=FPS):
    t = TRACERS[tracer] if isinstance(tracer, str) else tracer
    if not shutil.which("ffmpeg"):
        raise AnimationError("ffmpeg is not installed (macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt install ffmpeg)")
    frames, _ = t.run()
    durs = _scaled_durations(frames)
    lines = t.java.split("\n")
    check_code_fits(lines)
    base = _base(t, handle)
    cap_cache, code_cache = {}, {}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    start, prev, n_written = 0, None, 0

    def compose(f, viz):
        img = base.copy()
        img.paste(viz, (0, VIZ_Y))
        if f["caption"]:
            img.paste(cap_cache.setdefault(f["caption"], _caption_img(f["caption"])), CAP_BOX[:2])
        key = (f["line"], start)
        img.paste(code_cache.setdefault(key, _code_img(lines, f["line"], start)), CODE_BOX[:2])
        return img.tobytes()

    try:
        for f, dur in zip(frames, durs):
            start = _window_start(start, f["line"], len(lines))
            n = max(1, round(dur * fps))
            moving = (prev and f["viz"]["kind"] == "bars" and prev["viz"]["kind"] == "bars"
                      and prev["viz"]["order"] != f["viz"]["order"])
            tw = min(int(TWEEN_S * fps), n - 1) if moving else 0
            for k in range(tw):
                proc.stdin.write(compose(f, _viz_img(f, prev, (k + 1) / (tw + 1))))
            data = compose(f, _viz_img(f, prev, 1.0))
            for _ in range(n - tw):
                proc.stdin.write(data)
            n_written += n
            prev = f
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        proc.stderr.close()
        if proc.wait() != 0:
            raise AnimationError(f"ffmpeg failed: {err[-400:]}")
    except BrokenPipeError:
        raise AnimationError(f"ffmpeg stopped early: {proc.stderr.read().decode(errors='replace')[-400:]}")
    return {"path": str(out), "seconds": n_written / fps, "frames": n_written}


def render_poster_video(spec, out_path, handle="", fps=FPS, seconds=18.0):
    """The animated poster: each piece fades in, then the whole poster holds. About `seconds` long."""
    from .poster import poster_stages
    if not shutil.which("ffmpeg"):
        raise AnimationError("ffmpeg is not installed (macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt install ffmpeg)")
    stages = poster_stages(spec, handle)
    fade, first, last = 0.6, 2.0, 5.0
    reveals = len(stages) - 1
    hold = max(1.2, (seconds - first - last - fade * reveals) / max(1, reveals - 1))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    n_written = 0
    try:
        for i, img in enumerate(stages):
            if i:
                nf = round(fade * fps)
                for f in range(1, nf + 1):
                    proc.stdin.write(Image.blend(stages[i - 1], img, _ease(f / nf)).tobytes())
                n_written += nf
            n = round((first if i == 0 else last if i == reveals else hold) * fps)
            data = img.tobytes()
            for _ in range(n):
                proc.stdin.write(data)
            n_written += n
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        proc.stderr.close()
        if proc.wait() != 0:
            raise AnimationError(f"ffmpeg failed: {err[-400:]}")
    except BrokenPipeError:
        raise AnimationError(f"ffmpeg stopped early: {proc.stderr.read().decode(errors='replace')[-400:]}")
    return {"path": str(out), "seconds": n_written / fps, "frames": n_written}


def animation_text(tracer):
    """Text shown in the video, for the gate and the judge."""
    t = TRACERS[tracer] if isinstance(tracer, str) else tracer
    return f"{t.title}\n{t.subtitle}\n{t.complexity}\n\nJava code shown:\n{t.java}"


if __name__ == "__main__":
    import sys
    r = render_animation(sys.argv[1], sys.argv[2])
    print(r)
