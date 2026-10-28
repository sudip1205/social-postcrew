"""The voice's timeline: when each word of a scene is spoken, and so when each thing on the board should be drawn.

The voice is generated first, so every scene has its real length (the audio file). Inside a scene the word times are
estimated from the text: a word takes time in proportion to its letters, and a comma, a full stop or a question mark adds a
pause. That is close enough to start a box when the voice says its name, without asking the voice service for timestamps.
"""
import re
import shutil
import subprocess
from pathlib import Path

PAUSE = {",": 2.5, ";": 3.0, ":": 3.0, "—": 3.0, ".": 5.0, "!": 5.0, "?": 5.0}
SKIP = {"the", "and", "for", "with", "this", "that", "from", "into", "your", "you", "are", "its"}
LEAD = 0.15   # the pen starts a moment before the word is said


def word_times(narration, length, tail=0.35):
    """[(word, start, end)] spread over `length` seconds (minus a short silence at the end)."""
    words = str(narration or "").split()
    if not words:
        return []
    weights = [len(re.sub(r"\W", "", w)) + 1 + PAUSE.get(w[-1], 0) + (8 if w.endswith(("...", "\u2026")) else 0) for w in words]
    span, total, t, out = max(0.2, length - tail), sum(weights), 0.0, []
    for w, wt in zip(words, weights):
        d = span * wt / total
        out.append((w, t, t + d))
        t += d
    return out


def _key(word):
    return re.sub(r"[^a-z0-9+#]", "", word.lower())[:5]


def cue_time(label, times, after=0.0):
    """When the voice first says (a form of) one of the label's words after `after`, or None."""
    keys = {_key(w) for w in re.split(r"[\s/_\-:>]+", str(label or "")) if len(_key(w)) >= 2 and w.lower() not in SKIP}
    for w, start, _end in times:
        if start >= after and _key(w) in keys:
            return start
    return None


def schedule(items, times, length, tail=0.35, first=0.1, gap_cap=1.5, min_gap=None):
    """[(start, end)] for items drawn one after the other: [{"cue": words or None, "dur": seconds}].

    An item with a cue starts when the voice says it; one without is spread evenly between its neighbours. By default the pen draws
    one thing at a time; with min_gap the next thing may start that many seconds after the previous one started, while it is still
    animating (an animation, not a pen). Everything is finished before the scene's closing silence (the whole timeline is
    compressed if the voice mentions things too late to fit).
    """
    n = len(items)
    if not n:
        return []
    limit = max(0.5, length - tail)
    want, prev = [], 0.0
    for k, it in enumerate(items):
        c = None if k == 0 else cue_time(it.get("cue"), times, after=prev)
        want.append(None if c is None else max(first, c - LEAD))
        prev = c if c is not None else prev
    starts, ends, t = [], [], first
    k = 0
    while k < n:
        if k == 0 or want[k] is not None:
            s = max(t, want[k] if want[k] is not None else first)
            starts.append(s)
            ends.append(s + items[k]["dur"])
            t = ends[-1] if min_gap is None else starts[-1] + min_gap
            k += 1
            continue
        j = k   # a run of items without a cue: spread it up to the next cue (or the end of the scene)
        while j < n and want[j] is None:
            j += 1
        stop = want[j] if j < n else limit
        run = items[k:j]
        free = max(0.0, stop - t - sum(i["dur"] for i in run))
        gap = min(gap_cap, free / (len(run) + 1))
        for it in run:
            s = t + gap
            starts.append(s)
            ends.append(s + it["dur"])
            t = ends[-1] if min_gap is None else starts[-1] + min_gap
        k = j
    if max(ends) > limit:   # squeeze: scale the whole timeline to fit
        f = (limit - first) / max(0.01, max(ends) - first)
        starts = [first + (s - first) * f for s in starts]
        ends = [first + (e - first) * f for e in ends]
    return list(zip(starts, ends))


def progress(slots, t):
    """How much of each item is drawn at time t: a list of 0..1 (eased)."""
    out = []
    for s, e in slots:
        f = min(1.0, max(0.0, (t - s) / max(0.05, e - s)))
        out.append(f * f * (3 - 2 * f))
    return out


# ---------- measured against the real voice ----------
_quiet = {}


def silences(path, noise="-35dB", min_s=0.18):
    """[(start, end)] of the quiet stretches in an audio file (ffmpeg silencedetect); [] when it cannot be measured.
    Remembered per file, so drawing a scene again does not listen to its voice again."""
    try:
        key = (str(path), Path(path).stat().st_mtime_ns, noise, min_s)
    except OSError:
        return []
    if key not in _quiet:
        _quiet[key] = _silences(path, noise, min_s)
    return _quiet[key]


def _silences(path, noise, min_s):
    if not shutil.which("ffmpeg") or not path:
        return []
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", f"silencedetect=noise={noise}:d={min_s}",
                            "-f", "null", "-"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return []
    out, start = [], None
    for ln in r.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", ln)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", ln)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    if start is not None:   # quiet until the end of the file
        out.append((start, float("inf")))
    return out


def calibrate(words, length, quiet, tail=0.35):
    """The estimated word times pulled onto the real voice: the pauses after sentences (which the Voice step adds) are found in
    the audio, and each sentence is stretched or squeezed between them. Returns (words, True), or (words, False) when the audio
    does not show about one pause per sentence (then the estimate is all there is)."""
    ends = [i for i, (w, _s, _e) in enumerate(words[:-1]) if re.search(r"[.!?\u2026]$", w)]
    inner = [(a, b) for a, b in quiet if a > 0.3 and b < length - 0.15]
    if not ends or len(inner) < len(ends) or len(inner) > len(ends) * 2 + 1:
        return words, False
    if len(inner) > len(ends):   # commas and breaths also leave gaps: keep the longest ones, in order
        keep = sorted(sorted(inner, key=lambda x: x[1] - x[0], reverse=True)[:len(ends)])
        inner = keep
    trailing = next((a for a, b in quiet if b == float("inf") or b >= length - 0.05), None)
    speech_end = trailing if trailing and trailing > inner[-1][1] else max(inner[-1][1] + 0.2, length - tail)
    anchors = [(0.0, 0.0)] + [(words[i][2], b) for i, (a, b) in zip(ends, inner)] + [(words[-1][2], speech_end)]
    if any(x1 <= x0 or y1 <= y0 for (x0, y0), (x1, y1) in zip(anchors, anchors[1:])):
        return words, False

    def warp(t):
        for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
            if t <= x1:
                return y0 + (t - x0) * (y1 - y0) / (x1 - x0)
        return anchors[-1][1]
    return [(w, warp(s), warp(e)) for w, s, e in words], True


def voice_words(narration, length, audio=None, tail=0.35):
    """(word times, measured?) for one scene: the estimate, corrected by the scene's real audio file when there is one."""
    words = word_times(narration, length, tail)
    if audio and words:
        return calibrate(words, length, silences(audio), tail)
    return words, False
