"""What the voice says is what the picture shows, step by step: the checks the app runs itself (no AI) on every walk-through scene, whoever
wrote it (the Script Writer, the Storyboard Artist, the Quality Director's redesigns).

An explainer that says "the count reaches eight" over a picture that showed three of the eight teaches nothing and confuses the viewer. So:

  * COUNT ON SCREEN. A counter (count, matches, windows, pairs, ...) goes up by at most one per step, and starts where the scene before it
    left off (or at 0 or 1): every thing that is counted is shown being counted. A count that needs more steps than a scene holds needs a
    smaller example, not skipped steps.
  * SAY WHAT YOU SHOW. A number of boxes the voice names ("a ten box shelf") is the number of boxes drawn; a final count the voice names
    ("count reaches two") is the count the last step shows.
  * TRUE SUMS. A sum written on a step ("1 + 2 + 3 = 6") is correct, and when it adds up the lit boxes, it adds the numbers in those boxes.
  * ON CUE. Every step's 'say' words are words of the scene's narration, so the step happens when they are said.
"""
import re

from .render import timeline

COUNTER = re.compile(r"\b(count|matches|windows|pairs|hits|found|subarrays|valid)\b\s*(?:=|:|is)?\s*(\d+)", re.I)
EXPR = re.compile(r"(-?\d+(?:\s*[-+]\s*\d+)+)\s*=\s*(-?\d+)")
UNITS = r"(?:-|\s)?(?:boxes|box|cells?|elements?|slots?|squares?|tiles?)\b"
ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
        "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
NUM = r"(\d+|(?:" + "|".join(TENS) + r")(?:[-\s](?:" + "|".join(ONES[1:10]) + r"))?|" + "|".join(sorted(ONES, key=len, reverse=True)) + r")"


def number(word):
    """'eight' -> 8, 'twenty-one' -> 21, '12' -> 12; None when it is not a number."""
    w = str(word or "").lower().strip()
    if w.isdigit():
        return int(w)
    if w in ONES:
        return ONES.index(w)
    parts = re.split(r"[-\s]+", w)
    if parts and parts[0] in TENS:
        return TENS[parts[0]] + (ONES.index(parts[1]) if len(parts) > 1 and parts[1] in ONES[1:10] else 0)
    return None


def counters(step):
    """{name: value} of the counters a step shows (its memo first, then its note)."""
    out = {}
    for text in list(step.get("memo") or []) + [step.get("note") or ""]:
        for m in COUNTER.finditer(str(text)):
            out.setdefault(m.group(1).lower(), int(m.group(2)))
    return out


def last_counters(scene):
    seen = {}
    for st in scene.get("steps") or []:
        seen.update(counters(st))
    return seen


def counting_problems(steps, before=None):
    """A counter rises one shown step at a time, from where the scene before left it (or 0/1)."""
    before, now = dict(before or {}), {}
    for k, st in enumerate(steps, 1):
        for name, v in counters(st).items():
            prev = now.get(name, before.get(name, 0))
            if v > prev + 1:
                where = f"from {prev} to {v}" if name in now else f"at {v} (the scene before left it at {prev})" if name in before else f"at {v}"
                return [f"step {k}: {name} jumps {where}: show every one it counts, one step each (the box or window lit, its sum, "
                        f"the {name} going up by one). If that is more steps than one scene holds (12), use a smaller example"]
            now[name] = v
    return []


def sum_problems(cells, steps):
    """Sums written on steps are right, and a sum of the lit boxes adds the numbers in those boxes."""
    for k, st in enumerate(steps, 1):
        for m in EXPR.finditer(str(st.get("note") or "")):
            terms = re.findall(r"[-+]?\s*\d+", m.group(1))
            vals = [int(t.replace(" ", "")) for t in terms]
            if sum(vals) != int(m.group(2)):
                return [f"step {k}: the note says {m.group(0).strip()}, which is wrong ({' '.join(terms)} = {sum(vals)})"]
            if "-" in m.group(1).lstrip("-") or not cells:
                continue
            lit = sorted(set(st.get("active") or []) | set(st.get("found") or []))
            lit = [i for i in lit if isinstance(i, int) and 0 <= i < len(cells)]
            held = [cells[i] for i in lit]
            if len(lit) == len(vals) and all(re.fullmatch(r"-?\d+", str(h)) for h in held) and sorted(map(int, held)) != sorted(vals):
                return [f"step {k}: the note adds {m.group(1).strip()} but the lit boxes ({', '.join(map(str, lit))}) hold "
                        f"{', '.join(map(str, held))}: light the boxes it adds, or add the numbers they hold"]
    return []


def narration_problems(scene):
    """The numbers the voice says about the picture are the picture's."""
    text, out = str(scene.get("narration") or ""), []
    cells = scene.get("cells") or []
    for m in re.finditer(r"\b" + NUM + UNITS, text, re.I):
        n = number(m.group(1))
        if n is not None and n >= 2 and cells and n != len(cells) and not re.search(r"\b(window|of|each)\s*$", text[:m.start()], re.I):
            out.append(f"the voice says '{m.group(0).strip()}' but {len(cells)} boxes are drawn: draw exactly the boxes it talks about")
            break
    m = re.search(r"\bcount\s+(?:reaches|ends at|ends on|is|becomes|goes to|of|to|at)?\s*" + NUM + r"\b", text, re.I)
    said = number(m.group(1)) if m else None
    shown = last_counters(scene).get("count")
    if said is not None and shown is not None and said != shown:
        out.append(f"the voice says the count is {said} but the last step shows count = {shown}: show the count reaching {said}, one step per thing counted")
    return out


def cue_problems(scene):
    words = timeline.word_times(scene.get("narration") or "", 10.0)
    for k, st in enumerate(scene.get("steps") or [], 1):
        if words and timeline.cue_time(st.get("say"), words) is None:
            return [f"step {k}: say {st.get('say')!r} is not in the narration: 'say' is the narration's own words at that moment, so the step is "
                    f"drawn as they are spoken"]
    return []


def trace_problems(scene, before=None):
    """Everything wrong with a trace scene's story against its picture ([] when the picture tells what the voice says)."""
    cells, steps = [str(c) for c in scene.get("cells") or []], scene.get("steps") or []
    return (narration_problems(scene) + counting_problems(steps, before) + sum_problems(cells, steps) + cue_problems(scene))[:2]


def grid_problems(grid, narration=""):
    """A grid scene: true sums and on-cue steps."""
    steps = (grid or {}).get("steps") or []
    return (sum_problems([], steps) + cue_problems({"narration": narration, "steps": steps}))[:2]
