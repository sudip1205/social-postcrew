"""Quality checks on a finished video, with no AI: is there sound where the voice should be, is the voice clean, are the frames right.

Everything here is ffmpeg and Pillow, so it costs nothing and runs in seconds. It looks for what went wrong in earlier videos:

  sound   no audio at all; a stretch where the voice should speak but nothing is heard (missing sound); a long silence in the middle;
          loudness far from the target; clipping.
  frames  black frames; a frame that is frozen for many seconds; a scene whose picture is empty; things drawn too near the edge.
  format  the size and the length.

`inspect` returns findings [{"scene", "kind", "severity": "error" | "warn", "message"}] and a 0-100 score. An error is something a
viewer would notice at once and is worth fixing (or recording again); a warning is reported and left.
"""
import io
import re
import shutil
import subprocess

from PIL import Image, ImageChops, ImageFilter, ImageStat

LUFS_OK = (-19.0, -10.0)     # explainroo normalises to -14
SPEECH_DB = -42.0            # a voice span quieter than this (mean volume) is missing sound
SILENCE_S = 2.5              # a silence this long in the middle of the video
FREEZE_S = 10.0              # a frame that does not change for this long
PENALTY = {"error": 15, "warn": 4}


def _ffmpeg(args, timeout=300):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True, timeout=timeout)
    return r.stderr


def audio_facts(path):
    """{"has_audio", "lufs", "peak_db"} from ffmpeg's ebur128 (the whole file)."""
    log = _ffmpeg(["-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"])
    if "Stream #0" in log and "Audio:" not in log:
        return {"has_audio": False, "lufs": None, "peak_db": None}
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    peak = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)
    return {"has_audio": bool(lufs), "lufs": float(lufs[-1]) if lufs else None, "peak_db": float(peak[-1]) if peak else None}


def mean_volume(path, start, end):
    """Mean volume in dB of one stretch of the file, or None when it cannot be measured."""
    log = _ffmpeg(["-ss", f"{start:.3f}", "-t", f"{max(0.05, end - start):.3f}", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s+(-?[\d.]+) dB", log)
    return float(m.group(1)) if m else None


def silences(path, min_s=SILENCE_S, noise="-45dB"):
    """[(start, end)] of silences of at least min_s seconds."""
    log = _ffmpeg(["-i", str(path), "-vn", "-af", f"silencedetect=noise={noise}:d={min_s}", "-f", "null", "-"])
    out, start = [], None
    for ln in log.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", ln)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", ln)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    if start is not None:
        out.append((start, float("inf")))
    return out


def black_frames(path, min_s=0.6):
    log = _ffmpeg(["-i", str(path), "-an", "-vf", f"blackdetect=d={min_s}:pix_th=0.08", "-f", "null", "-"])
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]


def frozen(path, min_s=FREEZE_S):
    log = _ffmpeg(["-i", str(path), "-an", "-vf", f"freezedetect=n=-55dB:d={min_s}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    lens = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", log)]
    return list(zip(starts, lens))


def frame_at(path, t, width=270):
    """The frame at second t as a small RGB image, or None."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={width}:-1",
                        "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True, timeout=60)
    if r.returncode or not r.stdout:
        return None
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def ink(img, thr=38):
    """A mask of what is drawn (edges and bright shapes) as opposed to the smooth background: 1 where there is something."""
    g = img.convert("L")
    edges = g.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > thr else 0)
    bright = ImageChops.subtract(g, g.filter(ImageFilter.GaussianBlur(18))).point(lambda v: 255 if v > 28 else 0)
    return ImageChops.lighter(edges, bright)


def frame_facts(img, side=0.035):
    """{"coverage": share of the frame with something drawn, "edge": share of the left/right edge strips with something drawn}."""
    m = ink(img)
    w, h = m.size
    cover = ImageStat.Stat(m).mean[0] / 255
    strip = max(2, int(w * side))
    top, bottom = int(h * 0.06), int(h * 0.94)   # the corners hold the watermark and the app's buttons
    left, right = m.crop((0, top, strip, bottom)), m.crop((w - strip, top, w, bottom))
    edge = max(ImageStat.Stat(left).mean[0], ImageStat.Stat(right).mean[0]) / 255
    return {"coverage": cover, "edge": edge}


def inspect(path, spans, scenes, voiced=True, fmt="short", expect_seconds=None):
    """Check a finished video. spans: [(start, end)] of each scene's narration (where sound must be heard); scenes: [(start, end)] of
    each scene on screen. Returns (findings, score, facts)."""
    findings, facts = [], {}

    def add(scene, kind, severity, message):
        findings.append({"scene": scene, "kind": kind, "severity": severity, "message": message})
    if not shutil.which("ffmpeg"):
        return [], 100, {"skipped": "ffmpeg is not installed"}
    a = audio_facts(path)
    facts["audio"] = a
    if voiced:
        if not a["has_audio"]:
            add(None, "no_audio", "error", "the video has no sound at all")
        else:
            if a["lufs"] is not None and not LUFS_OK[0] <= a["lufs"] <= LUFS_OK[1]:
                add(None, "loudness", "error", f"the loudness is {a['lufs']:.1f} LUFS (should be about -14): too quiet or too loud")
            if a["peak_db"] is not None and a["peak_db"] > -0.1:
                add(None, "clipping", "error", f"the sound clips (peak {a['peak_db']:.1f} dBFS)")
            for i, (s, e) in enumerate(spans, 1):
                v = mean_volume(path, s, e)
                if v is not None and v < SPEECH_DB:
                    add(i, "missing_sound", "error", f"scene {i}: nothing is heard where the voice should speak ({s:.1f}s to {e:.1f}s, {v:.0f} dB)")
            gaps = silences(path)
            total = (expect_seconds or (scenes[-1][1] if scenes else 0)) or 0
            for s, e in gaps:
                inside_voice = [i for i, (vs, ve) in enumerate(spans, 1) if s < ve - 0.5 and e > vs + 0.5]
                if inside_voice and s > 0.5 and (e == float("inf") or e < total - 0.5):
                    add(inside_voice[0], "silence", "error", f"scene {inside_voice[0]}: {e - s:.1f}s of silence in the middle of the narration (from {s:.1f}s)")
    for s, e in black_frames(path):
        add(next((i for i, (a_, b_) in enumerate(scenes, 1) if a_ <= s < b_), None), "black", "error", f"black frames from {s:.1f}s to {e:.1f}s")
    for s, length in frozen(path):
        add(next((i for i, (a_, b_) in enumerate(scenes, 1) if a_ <= s < b_), None), "frozen", "warn", f"the picture does not change for {length:.0f}s from {s:.1f}s")
    for i, (s, e) in enumerate(scenes, 1):
        worst_edge, best_cover = 0.0, 0.0
        for frac in (0.5, 0.9):   # late in the scene: everything is drawn by then
            img = frame_at(path, s + (e - s) * frac)
            if img is None:
                continue
            f = frame_facts(img)
            worst_edge, best_cover = max(worst_edge, f["edge"]), max(best_cover, f["coverage"])
        if best_cover and best_cover < 0.012:
            add(i, "empty", "error", f"scene {i}: the picture is empty ({best_cover * 100:.1f}% of the frame has anything drawn)")
        if worst_edge > 0.06:
            add(i, "edge", "warn", f"scene {i}: something is drawn at the very edge of the frame ({worst_edge * 100:.0f}% of the side strips)")
    score = max(0, 100 - sum(PENALTY[f["severity"]] for f in findings))
    return findings, score, facts
