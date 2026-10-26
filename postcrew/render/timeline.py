"""The voice's timeline: when each word of a scene is spoken, and so when each thing on the board should be drawn.

The voice is generated first, so every scene has its real length (the audio file). Inside a scene the word times are
estimated from the text: a word takes time in proportion to its letters, and a comma, a full stop or a question mark adds a
pause. That is close enough to start a box when the voice says its name, without asking the voice service for timestamps.
"""
import re

PAUSE = {",": 2.5, ";": 3.0, ":": 3.0, "—": 3.0, ".": 5.0, "!": 5.0, "?": 5.0}
SKIP = {"the", "and", "for", "with", "this", "that", "from", "into", "your", "you", "are", "its"}
LEAD = 0.15   # the pen starts a moment before the word is said


def word_times(narration, length, tail=0.35):
    """[(word, start, end)] spread over `length` seconds (minus a short silence at the end)."""
    words = str(narration or "").split()
    if not words:
        return []
    weights = [len(re.sub(r"\W", "", w)) + 1 + PAUSE.get(w[-1], 0) for w in words]
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


def schedule(items, times, length, tail=0.35, first=0.1, gap_cap=1.5):
    """[(start, end)] for items drawn one after the other: [{"cue": words or None, "dur": seconds}].

    An item with a cue starts when the voice says it; one without is spread evenly between its neighbours. The pen draws one
    thing at a time, and everything is finished before the scene's closing silence (the whole timeline is compressed if the
    voice mentions things too late to fit).
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
            t = ends[-1]
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
            t = ends[-1]
        k = j
    if ends[-1] > limit:   # squeeze: scale the whole timeline to fit
        f = (limit - first) / max(0.01, ends[-1] - first)
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
