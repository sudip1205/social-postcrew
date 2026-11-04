"""A real two-dimensional board: the `grid` scene, for every problem set on a grid (a matrix, a maze, a game board, an image of cells).
A row of cells cannot say "above" or "below"; this draws the rows and columns as they are, and moves on it while the voice speaks.

The writer gives the board's rows and the moves, one step per beat of the narration. A step can light cells (active), mark the answer
(found), dim cells (out), put a labelled marker on a cell ("centre=2,3"), and draw PLUS shapes by their centre and arm ("2,3,1" is the
plus centred on row 2, column 3 with arms one cell long, 5 cells). The app works out every cell of a plus itself, so the picture is always
a true plus, and it refuses a plus that leaves the board or covers a blocked cell. Rows and columns count from 0.
"""
import re

MAX_SIDE = 10
MAX_STEPS = 12
CELL = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*$")
PLUS = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$")
MARK = re.compile(r"^\s*([^=]{1,12})=\s*(\d+)\s*,\s*(\d+)\s*$")

STEP = {
    "type": "object",
    "properties": {
        "say": {"type": "string", "description": "two or three words of the narration, said just as this step happens"},
        "active": {"type": "array", "items": {"type": "string"}, "maxItems": 40, "description": "cells being looked at now: 'row,col' ('2,3')"},
        "found": {"type": "array", "items": {"type": "string"}, "maxItems": 40, "description": "cells that are the answer: 'row,col'"},
        "out": {"type": "array", "items": {"type": "string"}, "maxItems": 60, "description": "cells ruled out or blocked now: 'row,col'"},
        "marks": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                  "description": "a labelled marker on a cell: 'centre=2,3' (label at most 12 characters)"},
        "pluses": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                   "description": "plus shapes drawn on the board: 'row,col,arm' ('2,3,1' = centred on row 2, column 3, arms of 1: 5 cells; arm 0 is one cell). "
                                  "Each keeps its own colour, in the order listed"},
        "note": {"type": "string", "description": "what this step shows, at most 60 characters: 'arm 1: area 5'"},
    },
    "required": ["say", "active", "found", "out", "marks", "pluses", "note"],
    "additionalProperties": False,
}
GRID = {
    "type": "object",
    "description": "a `grid` scene only: a real 2-D board (rows and columns) and the moves on it, drawn by the app",
    "properties": {
        "title": {"type": "string", "description": "the small heading over the board, at most 40 characters"},
        "rows": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_SIDE,
                 "description": "the board, one string per row, one character per cell, all rows the same length (2 to 10 each way): "
                                "['GGGGGG', 'GBBBGB', ...]. Copy the problem's example exactly"},
        "legend": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                   "description": "what each character means, 'G=good', 'B=bad' (shown under the board)"},
        "blocked": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                    "description": "characters no shape may cover ('B'); [] when every cell can be used"},
        "steps": {"type": "array", "items": STEP, "maxItems": MAX_STEPS, "description": "the moves, in the order the voice says them"},
    },
    "required": ["title", "rows", "legend", "blocked", "steps"],
    "additionalProperties": False,
}
START_S, PER_STEP_MIN = 0.6, 1.4


def plus_cells(r, c, arm):
    return [(r, c)] + [(r + d * k, c + e * k) for k in range(1, arm + 1) for d, e in ((-1, 0), (1, 0), (0, -1), (0, 1))]


def _cells(xs):
    out = []
    for x in xs or []:
        m = CELL.match(str(x))
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


def problems(v, n):
    p = f"scene {n}: "
    if not isinstance(v, dict):
        return [p + "a 'grid' scene needs its board in \"grid\": {title, rows, legend, blocked, steps}"]
    rows = v.get("rows") or []
    if not (2 <= len(rows) <= MAX_SIDE) or not all(isinstance(r, str) for r in rows):
        return [p + f"grid.rows is the board, 2 to {MAX_SIDE} rows, one string each"]
    w = len(rows[0])
    if not 2 <= w <= MAX_SIDE or any(len(r) != w for r in rows):
        return [p + f"grid.rows must all be the same length, 2 to {MAX_SIDE} characters (one per cell): {rows}"]
    blocked = set("".join(v.get("blocked") or []))
    inside = lambda rc: 0 <= rc[0] < len(rows) and 0 <= rc[1] < w
    out = []
    steps = v.get("steps") or []
    if not steps:
        out.append(p + "grid.steps: at least one step, so something happens on the board as the voice speaks")
    for k, st in enumerate(steps, 1):
        for key in ("active", "found", "out"):
            bad = [x for x in st.get(key) or [] if not CELL.match(str(x))]
            if bad:
                out.append(p + f"step {k}: {key} cells are 'row,col', not {bad[:2]}")
            off = [rc for rc in _cells(st.get(key)) if not inside(rc)]
            if off:
                out.append(p + f"step {k}: {key} cell {off[0][0]},{off[0][1]} is off the {len(rows)}x{w} board")
        for m in st.get("marks") or []:
            mm = MARK.match(str(m))
            if not mm or not inside((int(mm.group(2)), int(mm.group(3)))):
                out.append(p + f"step {k}: mark '{m}' must be 'label=row,col' on the board")
        for s in st.get("pluses") or []:
            mm = PLUS.match(str(s))
            if not mm:
                out.append(p + f"step {k}: plus '{s}' must be 'row,col,arm'")
                continue
            cells = plus_cells(*map(int, mm.groups()))
            if not all(inside(rc) for rc in cells):
                out.append(p + f"step {k}: the plus {s} runs off the {len(rows)}x{w} board")
            elif blocked and any(rows[r][c] in blocked for r, c in cells):
                r, c = next((r, c) for r, c in cells if rows[r][c] in blocked)
                out.append(p + f"step {k}: the plus {s} covers cell {r},{c}, which is '{rows[r][c]}' (blocked): a plus may only cover usable cells")
    return out


def min_seconds(v):
    return START_S + PER_STEP_MIN * len(v.get("steps") or [])


def props(v, when):
    """What Remotion draws. when(say, after) -> the time the words are said (render/remotion.py)."""
    steps, said = [], 0.0
    for st in v.get("steps") or []:
        t = when(st.get("say"), said)
        said = t
        pluses = []
        for s in st.get("pluses") or []:
            mm = PLUS.match(str(s))
            if mm:
                r, c, arm = map(int, mm.groups())
                pluses.append({"label": f"area {4 * arm + 1}", "cells": [list(x) for x in plus_cells(r, c, arm)]})
        marks = []
        for m in st.get("marks") or []:
            mm = MARK.match(str(m))
            if mm:
                marks.append({"name": mm.group(1).strip(), "at": [int(mm.group(2)), int(mm.group(3))]})
        steps.append({"t": round(t, 3), "active": [list(x) for x in _cells(st.get("active"))], "found": [list(x) for x in _cells(st.get("found"))],
                      "out": [list(x) for x in _cells(st.get("out"))], "marks": marks, "pluses": pluses, "note": str(st.get("note") or "")[:80]})
    return {"title": str(v.get("title") or "")[:60], "rows": [str(r) for r in v["rows"]], "legend": [str(x)[:20] for x in v.get("legend") or []],
            "blocked": list("".join(v.get("blocked") or [])), "steps": steps}
