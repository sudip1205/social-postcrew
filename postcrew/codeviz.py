"""Code plus a picture of what it does: the `codeviz` scene.

The screen shows the real code in an editor window and, under it, a live picture of the code running: a recursion tree growing call by call (repeated work
glows, a memo turns repeated calls into instant hits) or a table filling cell by cell. The line of code that is running is lit at every step.

The writer does not draw the picture, it describes the recursion in a few numbers (the function, n, how a call splits into smaller calls, the base
cases, how the answers combine) and says which line of its code is the call, the base case, the memo hit, the return and the table fill. This module
RUNS that description, so every node, count and value on screen is exactly what the code would do, and it lays the tree out and times the steps.
"""
import re

MAX_NODES = 40
COMBINE = ("sum", "min", "max")
KINDS = ("calls", "table")
LINE_KEYS = ("line_call", "line_base", "line_hit", "line_return", "line_fill")
START_S = 0.8     # the picture begins this long after the scene opens
TAIL_S = 1.2      # and rests this long before it ends
DT_MIN, DT_MAX = 0.14, 0.55

VIZ = {
    "type": "object",
    "description": "a `codeviz` scene only: the recursion or table that its code runs, as numbers. The app runs it and draws it",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS),
                 "description": "calls: the tree of calls the recursion makes (naive, or with a memo). table: bottom-up, one cell at a time"},
        "title": {"type": "string", "description": "the small heading over the picture, at most 40 characters: 'calls for f(5)'"},
        "fn": {"type": "string", "description": "the function's name as in the code, at most 8 characters: 'f', 'climb', 'dp'"},
        "n": {"type": "integer", "description": "the starting input. calls without a memo: 2 to 6 (the tree must stay small). with a memo or a table: 2 to 10"},
        "steps": {"type": "array", "items": {"type": "integer"}, "maxItems": 3,
                  "description": "how a call splits: [1, 2] means f(n) calls f(n-1) and f(n-2)"},
        "base": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                 "description": "the answers that need no more calls, written 'argument:value': ['0:1', '1:1']"},
        "combine": {"type": "string", "enum": list(COMBINE), "description": "how the answers of the smaller calls make this one's answer"},
        "plus": {"type": "integer", "description": "added after combining (1 for coin-change style, else 0)"},
        "memo": {"type": "boolean", "description": "calls only: true when the code remembers answers (a repeated call is answered at once from the memo)"},
        "line_call": {"type": "integer", "description": "the line of the code (counted from 1) where a call starts"},
        "line_base": {"type": "integer", "description": "the line of the base case; 0 if none"},
        "line_hit": {"type": "integer", "description": "the line that finds an answer in the memo; 0 if no memo"},
        "line_return": {"type": "integer", "description": "the line that works out and returns a call's answer"},
        "line_fill": {"type": "integer", "description": "table only: the line that fills a cell; 0 for calls"},
    },
    "required": ["kind", "title", "fn", "n", "steps", "base", "combine", "plus", "memo", *LINE_KEYS],
    "additionalProperties": False,
}


def parse_base(base):
    out = {}
    for b in base or []:
        m = re.fullmatch(r"\s*(-?\d+)\s*:\s*(-?\d+)\s*", str(b))
        if not m:
            return None
        out[int(m.group(1))] = int(m.group(2))
    return out


def _combine(how, vals, plus):
    if not vals:
        return plus
    return {"sum": sum, "min": min, "max": max}[how](vals) + plus


def simulate_calls(v):
    """The tree of calls the recursion makes: ({nodes, events}, None) or (None, why not)."""
    base, offsets, memo = parse_base(v.get("base")), [o for o in v.get("steps") or [] if o > 0], {}
    nodes, events = [], []
    state = {"seen": set()}

    def go(arg, parent):
        if len(nodes) >= MAX_NODES:
            raise OverflowError
        i = len(nodes)
        nodes.append({"arg": arg, "parent": parent, "value": None, "dup": arg in state["seen"], "hit": False})
        state["seen"].add(arg)
        events.append({"kind": "call", "node": i})
        if arg in base:
            nodes[i]["value"] = base[arg]
            events.append({"kind": "base", "node": i})
            return base[arg]
        if v.get("memo") and arg in memo:
            nodes[i].update(value=memo[arg], hit=True)
            events.append({"kind": "hit", "node": i})
            return memo[arg]
        vals = [go(arg - o, i) for o in offsets if arg - o >= 0]
        out = _combine(v["combine"], vals, int(v.get("plus") or 0))
        nodes[i]["value"] = out
        if v.get("memo"):
            memo[arg] = out
        events.append({"kind": "return", "node": i})
        return out

    try:
        go(int(v["n"]), -1)
    except OverflowError:
        return None, f"the tree has more than {MAX_NODES} calls: lower n (the naive tree of fib-like recursion grows fast)"
    return {"nodes": nodes, "events": events}, None


def simulate_table(v):
    base, offsets, cells = parse_base(v.get("base")), [o for o in v.get("steps") or [] if o > 0], []
    for arg in range(0, int(v["n"]) + 1):
        if arg in base:
            cells.append({"arg": arg, "value": base[arg], "from": [], "base": True})
        else:
            src = [arg - o for o in offsets if arg - o >= 0]
            cells.append({"arg": arg, "value": _combine(v["combine"], [cells[s]["value"] for s in src], int(v.get("plus") or 0)), "from": src, "base": False})
    return {"cells": cells}, None


def problems(v, code, n):
    """[] when the scene can be drawn. v: the scene's viz; code: its code; n: the scene number."""
    p = f"scene {n}: "
    if not isinstance(v, dict) or v.get("kind") not in KINDS:
        return [p + f"a 'codeviz' scene needs its 'viz' (kind {' or '.join(KINDS)}, fn, n, steps, base, combine and the line numbers of the code)"]
    out = []
    if not 1 <= len(str(v.get("fn") or "").strip()) <= 8:
        out.append(p + "viz.fn is the function's name, at most 8 characters")
    if not 3 <= len(str(v.get("title") or "").strip()) <= 40:
        out.append(p + "viz.title is 3 to 40 characters")
    base = parse_base(v.get("base"))
    if not base:
        return out + [p + "viz.base needs at least one base case written 'argument:value' ('0:1')"]
    offsets = v.get("steps") or []
    if not offsets or any(not isinstance(o, int) or o < 1 for o in offsets):
        return out + [p + "viz.steps lists how a call splits ([1, 2] means f(n-1) and f(n-2))"]
    top = 6 if v["kind"] == "calls" and not v.get("memo") else 10
    if not isinstance(v.get("n"), int) or not 2 <= v["n"] <= top:
        return out + [p + f"viz.n must be 2 to {top} for this kind of picture (it has to stay small enough to read)"]
    lines = len((code or "").strip().splitlines())
    for k in LINE_KEYS:
        if not isinstance(v.get(k), int) or not 0 <= v[k] <= lines:
            out.append(p + f"viz.{k} is a line number of the code (1 to {lines}), or 0 when that step does not exist")
    need = ("line_call", "line_base", "line_return") + (("line_hit",) if v.get("memo") else ()) if v["kind"] == "calls" else ("line_base", "line_fill")
    out += [p + f"viz.{k} must point at a line of the code" for k in need if not v.get(k)]
    if v["kind"] == "calls" and not out:
        _tree, why = simulate_calls(v)
        if why:
            out.append(p + why)
    return out


def _layout(nodes):
    """x in 0..1 (leaves spread, a parent above the middle of its children) and the depth of every node."""
    kids = {i: [] for i in range(len(nodes))}
    for i, nd in enumerate(nodes):
        if nd["parent"] >= 0:
            kids[nd["parent"]].append(i)
    xs, depth, leaf = {}, {}, [0]

    def place(i, d):
        depth[i] = d
        if not kids[i]:
            xs[i] = leaf[0]
            leaf[0] += 1
        else:
            for c in kids[i]:
                place(c, d + 1)
            xs[i] = sum(xs[c] for c in kids[i]) / len(kids[i])
    place(0, 0)
    width, height = max(1, leaf[0] - 1), max(1, max(depth.values()))
    return [{"x": round(xs[i] / width if width > 1 else 0.5, 4), "y": round(depth[i] / height, 4), "depth": depth[i]} for i in range(len(nodes))], leaf[0], max(depth.values()) + 1


def props(v, seconds):
    """What the screen draws: the picture's nodes or cells, and the timed events, each lighting a line of the code."""
    fn = str(v["fn"])
    avail = max(1.0, seconds - START_S - TAIL_S)
    if v["kind"] == "calls":
        sim, _ = simulate_calls(v)
        pos, leaves, levels = _layout(sim["nodes"])
        n_events = len(sim["events"])
        dt = max(DT_MIN, min(DT_MAX, avail / max(1, n_events)))
        line = {"call": v["line_call"], "base": v["line_base"], "hit": v["line_hit"], "return": v["line_return"]}
        events = [{"t": round(START_S + k * dt, 3), "kind": e["kind"], "node": e["node"], "line": line[e["kind"]],
                   "value": sim["nodes"][e["node"]]["value"]} for k, e in enumerate(sim["events"])]
        nodes = [{"label": f"{fn}({nd['arg']})", "parent": nd["parent"], "dup": nd["dup"], "hit": nd["hit"], "value": nd["value"], **pos[i]} for i, nd in enumerate(sim["nodes"])]
        return {"kind": "calls", "title": str(v["title"]), "nodes": nodes, "events": events, "leaves": leaves, "levels": levels, "memo": bool(v.get("memo")),
                "calls": sum(1 for e in sim["events"] if e["kind"] == "call")}
    sim, _ = simulate_table(v)
    dt = max(DT_MIN, min(0.8, avail / max(1, len(sim["cells"]))))
    cells = [{"label": f"{fn}({c['arg']})" if len(str(fn)) <= 4 else str(c["arg"]), "arg": c["arg"], "value": c["value"], "from": c["from"], "t": round(START_S + k * dt, 3),
              "line": v["line_base"] if c["base"] else v["line_fill"]} for k, c in enumerate(sim["cells"])]
    return {"kind": "table", "title": str(v["title"]), "cells": cells, "combine": v["combine"], "plus": int(v.get("plus") or 0)}
