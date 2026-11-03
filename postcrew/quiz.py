"""The quiz Short: "A or B? Which is better?", the format every YouTube Short is made in.

A Short is an intro, three to five ROUNDS, and the closing card (with the answer key). A round is one `versus` scene: two tiles, A and B, show the
same task done two ways at the same time while the voice asks the question and counts down ("Three, two, one."); then the better one is marked, the
other dims, the demo replays slowly and the voice explains why. This module is the one place that knows the shape of a round: what the writer
may put in it (`TILE`, `VERSUS`), the checks (`round_problems`, `problems`), the narration it is spoken as (`compose`) and the numbers the
Remotion scene is drawn from (`versus_props`).
"""
import math
import re

KINDS = ("trace", "link", "curve", "bars")
FUNCS = {
    "1": lambda n: 1.0,
    "log n": lambda n: math.log2(n + 1),
    "n": lambda n: float(n),
    "n log n": lambda n: n * math.log2(n + 1),
    "n^2": lambda n: float(n * n),
    "2^n": lambda n: 2.0 ** n,
}
ROUNDS_MIN, ROUNDS_MAX = 3, 5
ROUND_PARTS = ("idea", "example", "mistake")
COUNTDOWN = "Three, two, one."
_COUNT = re.compile(r"three[,.…\s]+two[,.…\s]+one[.!]?\s*$", re.I)
DEMO_S = 2.6          # how long a demo takes to play once (the pick phase plays it live; the reveal replays it slower)
START_S = 0.9         # the demo starts this long after the scene opens
NAMES = {"trace": "steps over the data", "link": "packets between two boxes", "curve": "a growth curve", "bars": "bars to compare"}

STEP = {
    "type": "object",
    "properties": {
        "active": {"type": "array", "items": {"type": "integer"}, "description": "cells looked at in this step (counted from 0)"},
        "found": {"type": "array", "items": {"type": "integer"}, "description": "cells that are the answer (green); [] until it is found"},
        "out": {"type": "array", "items": {"type": "integer"}, "description": "cells ruled out so far (dimmed)"},
        "note": {"type": "string", "description": "the sum or the decision, at most 40 characters: '8 + 7 = 15, no'"},
    },
    "required": ["active", "found", "out", "note"],
    "additionalProperties": False,
}
TILE = {
    "type": "object",
    "description": "one side of a round. A and B use the SAME kind so the viewer compares like with like",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS),
                 "description": "trace: cells with the steps being taken over them. link: packets going between two boxes, faster or slower. curve: a growth curve "
                                "(O of n and so on). bars: two to four bars of different size"},
        "sub": {"type": "string", "description": "the small line above the picture, at most 36 characters: 'nested loops, every pair'"},
        "counter": {"type": "string", "description": "what the counter at the top counts, one word in capitals: CHECKS, STEPS, LOOKS, SERVED"},
        "cells": {"type": "array", "items": {"type": "string"}, "maxItems": 12, "description": "trace only: the data, at most 5 characters each"},
        "steps": {"type": "array", "items": STEP, "maxItems": 12, "description": "trace only: what happens, one entry per move (the counter counts them)"},
        "src": {"type": "string", "description": "link only: the box the packets leave, at most 12 characters"},
        "dst": {"type": "string", "description": "link only: the box they go to, at most 12 characters"},
        "ms": {"type": "number", "description": "link only: the time one packet takes in milliseconds. A smaller number runs faster on screen"},
        "fail": {"type": "boolean", "description": "link only: true when the packets are lost on the way (the box is down)"},
        "fn": {"type": "string", "enum": list(FUNCS), "description": "curve only: how the work grows with n"},
        "label": {"type": "string", "description": "curve: the name drawn beside the line ('O(n)', at most 10 characters); bars: the unit ('ms')"},
        "bars": {"type": "array", "items": {"type": "string"}, "maxItems": 4, "description": "bars only: one to four 'Label|number' (label at most 16 characters), for example 'Database|120'. Each tile may show one bar for its own way: the bars of A and B share one scale"},
    },
    "required": ["kind", "sub", "counter", "cells", "steps", "src", "dst", "ms", "fail", "fn", "label", "bars"],
    "additionalProperties": False,
}
VERSUS = {
    "type": "object",
    "description": "a `versus` scene only: one round of the quiz",
    "properties": {
        "pick": {"type": "string", "description": "what the voice says while the viewer chooses: the question, then 'Pick A or B.' (the app adds 'Three, two, one.')"},
        "reveal": {"type": "string", "description": "what the voice says after the answer is shown: which one wins and why, in plain spoken sentences"},
        "a": TILE, "b": TILE,
        "winner": {"type": "string", "enum": ["A", "B"]},
        "badge": {"type": "string", "description": "the small label on the winner, at most 30 characters, in capitals: 'ONE PASS, NO NESTED LOOP'"},
        "caption": {"type": "string", "description": "the one line shown under the tiles after the answer, at most 90 characters"},
        "name": {"type": "string", "description": "the round's name in the answer key, at most 22 characters: 'Two Sum'"},
        "answer": {"type": "string", "description": "the answer in the key, at most 34 characters: 'B: hash map, one pass'"},
    },
    "required": ["pick", "reveal", "a", "b", "winner", "badge", "caption", "name", "answer"],
    "additionalProperties": False,
}


def count_in(pick):
    return bool(_COUNT.search(pick or ""))


def pick_text(v):
    """The spoken question, always ending with the countdown the screen counts with."""
    pick = " ".join(str((v or {}).get("pick") or "").split())
    if not pick:
        return ""
    return pick if count_in(pick) else f"{pick} {COUNTDOWN}"


def compose(sc):
    """A round is spoken as its question (with the countdown), then its explanation."""
    v = sc.get("versus") or {}
    return " ".join(x for x in (pick_text(v), " ".join(str(v.get("reveal") or "").split())) if x)


# ---------- the checks ----------
def tile_problems(t, tag):
    """tag: 'A' or 'B'. [] when the tile can be drawn."""
    out, kind = [], (t or {}).get("kind")
    if kind not in KINDS:
        return [f"tile {tag}: kind must be one of {', '.join(KINDS)}"]
    if not 3 <= len(str(t.get("sub") or "").strip()) <= 36:
        out.append(f"tile {tag}: 'sub' is the small line above the picture, 3 to 36 characters")
    if len(str(t.get("counter") or "")) > 10:
        out.append(f"tile {tag}: 'counter' is one short word (CHECKS, STEPS), at most 10 characters")
    if kind == "trace":
        cells, steps = [str(c) for c in t.get("cells") or []], t.get("steps") or []
        if not 2 <= len(cells) <= 12 or any(not c.strip() or len(c) > 5 for c in cells):
            out.append(f"tile {tag}: a trace needs 2 to 12 cells of at most 5 characters")
        elif not 2 <= len(steps) <= 12:
            out.append(f"tile {tag}: a trace needs 2 to 12 steps (each one a move the counter counts)")
        else:
            for n, st in enumerate(steps, 1):
                idx = [i for k in ("active", "found", "out") for i in st.get(k) or []]
                if not st.get("active") or any(not 0 <= i < len(cells) for i in idx):
                    out.append(f"tile {tag}: step {n} must name the cells it looks at, counted from 0 to {len(cells) - 1}")
                    break
                if len(str(st.get("note") or "")) > 40:
                    out.append(f"tile {tag}: step {n}: the note is at most 40 characters")
                    break
    elif kind == "link":
        if not all(0 < len(str(t.get(k) or "").strip()) <= 12 for k in ("src", "dst")):
            out.append(f"tile {tag}: a link needs 'src' and 'dst' boxes of at most 12 characters")
        if not isinstance(t.get("ms"), (int, float)) or isinstance(t.get("ms"), bool) or not 0 < t["ms"] <= 100000:
            out.append(f"tile {tag}: a link needs 'ms', the milliseconds one packet takes (a number above 0)")
    elif kind == "curve":
        if t.get("fn") not in FUNCS:
            out.append(f"tile {tag}: a curve's 'fn' must be one of {', '.join(FUNCS)}")
        if not 1 <= len(str(t.get("label") or "")) <= 10:
            out.append(f"tile {tag}: a curve needs a 'label' of at most 10 characters ('O(n)')")
    elif kind == "bars":
        parsed = [parse_bar(b) for b in t.get("bars") or []]
        if not 1 <= len(parsed) <= 4 or any(p is None or len(p[0]) > 16 for p in parsed):
            out.append(f"tile {tag}: bars need 1 to 4 entries written 'Label|number' (label at most 16 characters)")
    return out


def parse_bar(text):
    label, _, num = str(text).partition("|")
    try:
        value = float(num.strip().replace(",", ""))
    except ValueError:
        return None
    return (label.strip(), value) if label.strip() and value >= 0 else None


def round_problems(sc, n):
    """One `versus` scene: n is its scene number (from 1)."""
    v, out = sc.get("versus") or {}, []
    if not v:
        return [f"scene {n}: a 'versus' scene needs its 'versus' round (pick, reveal, the tiles a and b, winner, badge, caption, name, answer)"]
    pick, reveal = " ".join(str(v.get("pick") or "").split()), " ".join(str(v.get("reveal") or "").split())
    if not 4 <= len(pick.split()) <= 40:
        out.append(f"scene {n}: 'pick' is the spoken question, 4 to 40 words, ending 'Pick A or B.'")
    if not 8 <= len(reveal.split()) <= 60:
        out.append(f"scene {n}: 'reveal' is the spoken explanation, 8 to 60 words")
    for k, limit in (("badge", 30), ("caption", 90), ("name", 22), ("answer", 34)):
        if not 2 <= len(str(v.get(k) or "").strip()) <= limit:
            out.append(f"scene {n}: '{k}' needs 2 to {limit} characters")
    if v.get("winner") not in ("A", "B"):
        out.append(f"scene {n}: 'winner' must be A or B")
    if not 3 <= len(str(sc.get("on_screen") or "").strip()) <= 60:
        out.append(f"scene {n}: 'on_screen' is the round's heading, 3 to 60 characters (mark the key words with *stars*)")
    a, b = v.get("a") or {}, v.get("b") or {}
    out += [f"scene {n}: {p}" for tag, t in (("A", a), ("B", b)) for p in tile_problems(t, tag)]
    if a.get("kind") in KINDS and a.get("kind") != b.get("kind"):
        out.append(f"scene {n}: tiles A and B must be the same kind ({a.get('kind')} against {b.get('kind')}): compare like with like")
    if a.get("kind") == "curve" and a.get("fn") == b.get("fn"):
        out.append(f"scene {n}: both curves grow the same way: the two tiles must show different growth")
    return out


def problems(scenes, spec):
    """The checks of a whole quiz Short: intro, three to five rounds, the closing card, and the answers not always the same letter."""
    out = []
    rounds = [sc for sc in scenes if sc.get("layout") == "versus"]
    if not ROUNDS_MIN <= len(rounds) <= ROUNDS_MAX:
        out.append(f"a Short is a quiz of {ROUNDS_MIN} to {ROUNDS_MAX} rounds (scenes with layout 'versus'): there are {len(rounds)}")
    for i, sc in enumerate(scenes, 1):
        first, last = i == 1, i == len(scenes)
        if sc.get("layout") == "versus":
            if sc.get("part") not in ROUND_PARTS:
                out.append(f"scene {i}: a round's part is idea, example or mistake")
        elif not (first or last):
            out.append(f"scene {i}: between the introduction and the closing card a Short has only 'versus' rounds, not '{sc.get('layout')}'")
        elif first and sc.get("layout") not in ("title", "statement"):
            out.append("the first scene is the spoken introduction (layout statement): it states the problem and promises the quiz, it is not a round")
    if len(rounds) >= 3 and len({(sc.get("versus") or {}).get("winner") for sc in rounds}) < 2:
        out.append("every round has the same winner: make the quiz honest, with the better one on A in some rounds and on B in others")
    names = [str((sc.get("versus") or {}).get("name") or "").lower() for sc in rounds]
    if len(set(names)) != len(names):
        out.append("two rounds have the same name: each round is a different comparison")
    return out


# ---------- what the scene is drawn from ----------
def curve_points(fn, ymax, n=10, samples=48):
    f = FUNCS[fn]
    return [[round(i / samples, 4), round(min(1.0, f(n * i / samples) / ymax), 4)] for i in range(samples + 1)]


def tile_props(t, other):
    """The tile with what the screen needs: step length, curve points on a scale shared with the other tile, bar fractions."""
    kind = t["kind"]
    out = {"kind": kind, "sub": str(t.get("sub") or ""), "counter": str(t.get("counter") or "").upper()}
    if kind == "trace":
        steps = t.get("steps") or []
        out.update(cells=[str(c) for c in t.get("cells") or []], step_s=round(max(0.2, min(0.6, DEMO_S / max(1, len(steps)))), 3),
                   steps=[{"active": st.get("active") or [], "found": st.get("found") or [], "out": st.get("out") or [], "note": str(st.get("note") or "")}
                          for st in steps])
    elif kind == "link":
        ms = float(t.get("ms") or 100)
        om = float(other.get("ms") or 100)
        out.update(src=str(t["src"]), dst=str(t["dst"]), ms=ms, fail=bool(t.get("fail")), period=round(max(0.25, min(1.6, 0.25 + ms / 150.0)), 3),
                   tone="bad" if t.get("fail") or ms > om else "good" if ms < om else "")
    elif kind == "curve":
        ymax = max(FUNCS[x["fn"]](10) for x in (t, other) if x.get("fn") in FUNCS)
        ymax = min(ymax, 100.0)
        mine, theirs = FUNCS[t["fn"]](10), FUNCS[other["fn"]](10) if other.get("fn") in FUNCS else FUNCS[t["fn"]](10)
        out.update(label=str(t["label"]), points=curve_points(t["fn"], ymax), ymax=round(ymax, 2), tone="bad" if mine > theirs else "good" if mine < theirs else "")
    elif kind == "bars":
        bars = [p for p in (parse_bar(b) for b in t.get("bars") or []) if p]
        top = max([p[1] for x in (t, other) for p in (parse_bar(b) for b in x.get("bars") or []) if p] or [1.0]) or 1.0
        out.update(unit=str(t.get("label") or ""), bars=[{"label": lbl, "value": val, "frac": round(val / top, 4)} for lbl, val in bars])
    return out


def versus_props(sc, words, number, total, length):
    """The `versus` of the props file. words: [(word, start, end)] of the scene's narration; number/total: this round and how many there are."""
    v = sc.get("versus") or {}
    pick = pick_text(v)
    n = len(pick.split())
    if len(words) > n:
        reveal = words[n][1]
        count = [words[n - 3 + k][1] for k in range(3)] if n >= 3 else []
    else:   # the voice words are not one to one with the text: reveal at the same share of the scene, count in the last three seconds
        reveal = length * n / max(1, n + len(str(v.get("reveal") or "").split()))
        count = []
    if not count or any(count[k] >= count[k + 1] for k in range(2)) or count[-1] >= reveal:
        count = [max(0.3, reveal - 3 + k) for k in range(3)] if reveal >= 3.3 else []
    return {"round": number, "rounds": total, "a": tile_props(v["a"], v["b"]), "b": tile_props(v["b"], v["a"]), "winner": v["winner"],
            "badge": str(v.get("badge") or "").upper(), "caption": str(v.get("caption") or ""), "reveal_at": round(reveal, 3),
            "count_at": [round(c, 3) for c in count], "demo_s": DEMO_S, "start_s": START_S}


def answers(scenes):
    """The answer key shown on the closing card."""
    return [{"name": str((sc.get("versus") or {}).get("name") or ""), "answer": str((sc.get("versus") or {}).get("answer") or "")}
            for sc in scenes if sc.get("layout") == "versus"]
