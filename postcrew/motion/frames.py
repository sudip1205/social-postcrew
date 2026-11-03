"""Looking at video frames without AI: probe a file, find its cuts, grab frames, measure them and lay them out as contact sheets.

Used two ways:
  - the Reference Library (motion/library.py) measures a reference video: its cuts, how long a shot lasts, its colours and how much of the
    screen it fills, and makes the sheets a vision model describes;
  - the Quality Director (agents/quality.py) grabs frames of every scene of a finished video and measures what a viewer would notice at once:
    an empty scene, a picture that only fills a corner of the screen, a picture that does not change for many seconds.

Everything here is ffmpeg and Pillow: free, offline, seconds.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

SMALL = (135, 240)          # measuring size for a 9:16 frame (a 16:9 one is turned around)
CONTENT_DIFF = 60           # a pixel this far (sum of |R|+|G|+|B|) from the page colour is content
CAPTION_ZONE = 0.21         # the bottom part of a vertical frame that belongs to the captions
TOP_ZONE = 0.04             # a thin top band (safe area) is not counted either


class FrameError(RuntimeError):
    pass


def have_ffmpeg():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    return r


def probe(path):
    """{"seconds", "width", "height", "fps", "has_audio"} of a video file."""
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
              "-of", "json", str(path)], 60)
    if r.returncode != 0:
        raise FrameError(f"ffprobe could not read {Path(path).name}: {r.stderr.strip()[-300:]}")
    d = json.loads(r.stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        raise FrameError(f"{Path(path).name} has no video stream")
    num, _, den = str(v.get("r_frame_rate", "30/1")).partition("/")
    fps = round(float(num) / float(den or 1), 2) if float(den or 1) else 30.0
    return {"seconds": round(float((d.get("format") or {}).get("duration") or 0), 2), "width": int(v["width"]),
            "height": int(v["height"]), "fps": fps,
            "has_audio": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}


def detect_cuts(path, threshold=0.27, min_shot=0.4):
    """Times (s) where the picture changes enough to count as a new shot (ffmpeg's scene score)."""
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
              f"scale=270:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"], 900)
    times, last = [], -1.0
    for m in re.finditer(r"pts_time:([\d.]+)", r.stderr):
        t = float(m.group(1))
        if t - last >= min_shot:
            times.append(round(t, 2))
            last = t
    return times


def shots(path, seconds=None, threshold=0.27, max_shots=60):
    """[(start, end)] shots of a video, from its cuts. Very long shots are kept whole; too many shots are merged evenly.
    Motion graphics on a dark page change softly (a fade, a card sliding in) and hardly register at a camera-footage threshold: when
    fewer than one cut per 15 seconds is found, the threshold is lowered step by step."""
    seconds = seconds or probe(path)["seconds"]
    for th in (threshold, 0.12, 0.06):
        cuts = [t for t in detect_cuts(path, th) if 0.3 < t < seconds - 0.3]
        if len(cuts) >= seconds / 15:
            break
    edges = [0.0] + cuts + [seconds]
    out = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1) if edges[i + 1] - edges[i] > 0.05]
    while len(out) > max_shots:   # merge the shortest shot with its neighbour
        i = min(range(len(out) - 1), key=lambda k: (out[k][1] - out[k][0]) + (out[k + 1][1] - out[k + 1][0]))
        out[i:i + 2] = [(out[i][0], out[i + 1][1])]
    return out


def grab(path, t, out_path, width=360):
    """One frame at time t (s), scaled to `width`, saved as PNG."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1",
              "-vf", f"scale={width}:-2", str(out_path)], 120)
    if r.returncode != 0 or not out_path.exists():
        raise FrameError(f"could not grab a frame at {t:.1f}s: {r.stderr.strip()[-200:]}")
    return out_path


# ---------- measuring one frame ----------
def _page(img):
    """The page colour: the most common colour of the four corners."""
    w, h = img.size
    px = [img.getpixel((x, y)) for x in (1, w - 2) for y in (1, h - 2)]
    return max(set(px), key=px.count)


def content_mask(img):
    """A 1-bit-ish mask ("L", 255 = content) of what differs from the page, at measuring size."""
    small = img.convert("RGB").resize(SMALL if img.height >= img.width else SMALL[::-1], Image.BILINEAR)
    page = Image.new("RGB", small.size, _page(small))
    diff = ImageChops.difference(small, page).convert("RGB")
    r, g, b = diff.split()
    total = ImageChops.add(ImageChops.add(r, g, scale=1.0), b, scale=1.0)   # saturates at 255: fine for a threshold
    return total.point(lambda v: 255 if v >= CONTENT_DIFF else 0)


def measure(img):
    """What a viewer sees at once in one frame, without AI:
    fill      share of the picture area (captions and top band excluded) that is content (0-1)
    height    share of the picture area's height between the highest and lowest content (0-1)
    width     the same across
    palette   up to 5 main colours (#rrggbb), page first
    bright    mean brightness 0-255"""
    if not isinstance(img, Image.Image):
        with Image.open(img) as f:
            img = f.convert("RGB")
    img = img.convert("RGB")
    mask = content_mask(img)
    w, h = mask.size
    vertical = h >= w
    top = int(h * TOP_ZONE)
    bottom = int(h * (1 - CAPTION_ZONE)) if vertical else int(h * 0.86)
    area = mask.crop((0, top, w, bottom))
    hist = area.histogram()
    fill = hist[255] / float(area.size[0] * area.size[1] or 1)
    rows = [y for y in range(area.size[1]) if sum(1 for x in range(area.size[0]) if area.getpixel((x, y))) >= max(2, area.size[0] // 60)]
    cols = [x for x in range(area.size[0]) if sum(1 for y in range(area.size[1]) if area.getpixel((x, y))) >= max(2, area.size[1] // 60)]
    height = (rows[-1] - rows[0] + 1) / area.size[1] if rows else 0.0
    width = (cols[-1] - cols[0] + 1) / area.size[0] if cols else 0.0
    return {"fill": round(fill, 4), "height": round(height, 3), "width": round(width, 3),
            "palette": palette(img), "bright": round(ImageStat.Stat(img.convert("L")).mean[0], 1)}


def palette(img, n=5):
    """Main colours of a frame, most used first."""
    q = img.convert("RGB").resize((96, 96)).quantize(colors=n + 3, method=Image.MEDIANCUT)
    pal = q.getpalette()
    counts = sorted(q.getcolors() or [], reverse=True)
    out = []
    for _count, idx in counts:
        r, g, b = pal[idx * 3: idx * 3 + 3]
        hexc = f"#{r:02x}{g:02x}{b:02x}"
        if all(sum(abs(int(hexc[i:i + 2], 16) - int(o[i:i + 2], 16)) for i in (1, 3, 5)) > 40 for o in out):
            out.append(hexc)
        if len(out) >= n:
            break
    return out


def change(a, b):
    """How different the pictures of two frames are, 0 (identical) to 255 (opposite): mean absolute difference at measuring size,
    captions left out."""
    def load(x):
        if isinstance(x, Image.Image):
            return x
        with Image.open(x) as f:
            return f.convert("RGB")
    a, b = load(a), load(b)
    size = SMALL if a.height >= a.width else SMALL[::-1]
    d = ImageChops.difference(a.convert("L").resize(size), b.convert("L").resize(size))
    w, h = size
    d = d.crop((0, int(h * TOP_ZONE), w, int(h * (1 - CAPTION_ZONE)) if h >= w else int(h * 0.86)))   # the captions change anyway
    return round(ImageStat.Stat(d).mean[0], 2)


# ---------- contact sheets ----------
def _font(size):
    root = Path(__file__).resolve().parent.parent / "render" / "fonts"
    for name in ("Inter-SemiBold.ttf", "Inter-Bold.ttf", "Inter.ttf"):
        if (root / name).exists():
            return ImageFont.truetype(str(root / name), size)
    for f in root.glob("*.ttf"):
        return ImageFont.truetype(str(f), size)
    return ImageFont.load_default()


def sheet(cells, out_path, cols=4, cell_width=360):
    """A contact sheet: cells = [(label, image path)], laid out `cols` across, each labelled above. Returns the path."""
    if not cells:
        raise FrameError("nothing to put on a contact sheet")
    with Image.open(cells[0][1]) as first:
        fw, fh = first.size
    cw = cell_width
    ch = round(fh * cw / fw)
    label_h = 34
    rows = (len(cells) + cols - 1) // cols
    W, H = cols * cw + (cols + 1) * 8, rows * (ch + label_h) + (rows + 1) * 8
    out = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(out)
    font = _font(20)
    for k, (label, path) in enumerate(cells):
        x = 8 + (k % cols) * (cw + 8)
        y = 8 + (k // cols) * (ch + label_h + 8)
        d.text((x + 2, y + 6), label, fill="#111111", font=font)
        with Image.open(path) as src:
            im = src.convert("RGB").resize((cw, ch), Image.LANCZOS)
        out.paste(im, (x, y + label_h))
        d.rectangle((x - 1, y + label_h - 1, x + cw, y + label_h + ch), outline="#999999")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, "PNG", optimize=True)
    return out_path
