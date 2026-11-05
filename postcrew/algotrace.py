"""Run the code, draw what happened: the `run` scene, for algorithm videos.

The Script Writer writes the solution code and marks ONE line with `# step`; the app runs that code on the example (in a separate, locked-down
Python process) and records every time the marked line finishes: the array, the pointers, the variables, and the calculation that changed
them ("current = max(4, -2 + 4) = 4", worked out from the real values). Those recorded steps ARE the picture: nothing on the board is typed by
hand, so a step cannot be skipped, a sum cannot be wrong and a count cannot jump. The writer then narrates the steps, one sentence each, and
the app times each step to its sentence.

The scene's "run" object says what to draw:
  call      the call that runs the code on the example: "max_subarray([-2, 1, -3, 4])"
  array     the variable drawn as the row of cells (a list or a string), or as a board (a list of rows) when kind is "grid"
  pointers  integer variables drawn as arrows under their cell (["i", "j"]); on a grid: the row and column variables
  window    two integer variables: the cells from the first to the second are lit (["start", "end"]), or []
  show      up to 4 variables shown as big tiles (["current", "best"])
  steps     which recorded steps this scene shows: "1-5" (a scene shows at most 12; the next scene can show "6-9")
"""
import ast
import hashlib
import json
import re
import subprocess
import sys

MAX_SCENE_STEPS = 12
MIN_WORDS = 5   # each step's sentence: what is looked at, the calculation, the result
TIMEOUT_S = 10

RUN = {
    "type": "object",
    "description": "a `run` scene only (algorithm videos): the app RUNS the scene's code on the example and draws every step it really takes",
    "properties": {
        "call": {"type": "string", "description": "the call that runs the code on the example, exactly: 'max_subarray([-2, 1, -3, 4, -1])'"},
        "kind": {"type": "string", "enum": ["array", "grid"], "description": "array: one row of cells (a list or a string). grid: a board (a list of rows)"},
        "array": {"type": "string", "description": "the name of the variable drawn as the cells: 'nums'"},
        "pointers": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                     "description": "integer variables drawn as arrows under their cell: ['i'] (a grid: ['r', 'c'] for row and column)"},
        "window": {"type": "array", "items": {"type": "string"}, "maxItems": 2,
                   "description": "two integer variables: the cells from the first to the second are lit, ['start', 'end']; [] for none"},
        "show": {"type": "array", "items": {"type": "string"}, "maxItems": 4, "description": "variables shown as big tiles: ['current', 'best']"},
        "steps": {"type": "string", "description": "which of the recorded steps this scene shows, 'first-last', counted from 1: '1-5'"},
    },
    "required": ["call", "kind", "array", "pointers", "window", "show", "steps"],
    "additionalProperties": False,
}

# The program run in the child process. It reads {code, call} on stdin and writes the recorded steps as JSON on stdout.
RUNNER = r'''
import ast, json, sys, io, traceback

def main():
    job = json.loads(sys.stdin.read())
    code, call = job["code"], job["call"]
    lines = code.splitlines()
    marks = {i + 1 for i, l in enumerate(lines) if "# step" in l}
    tree = ast.parse(code)
    assigns = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and getattr(node, "value", None) is not None:
            assigns[node.lineno] = node

    def simple(v, depth=0):
        if isinstance(v, bool) or v is None:
            return v
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            return v if len(v) <= 60 else None
        if isinstance(v, (list, tuple)) and len(v) <= 40 and depth < 2:
            out = [simple(x, depth + 1) for x in v]
            return out if all(x is not None or y is None for x, y in zip(out, v)) else None
        if isinstance(v, dict) and len(v) <= 12 and depth < 1:
            out = {str(k): simple(x, depth + 1) for k, x in v.items()}
            return out if all(x is not None for x in out.values()) else None
        return None

    def snap(f):
        out = {}
        for k, v in f.f_locals.items():
            s = simple(v)
            if s is not None or v is None:
                out[k] = s
        return out

    class Fill(ast.NodeTransformer):
        def __init__(self, env, g):
            self.env, self.g = env, g
        def visit_Call(self, node):
            node.args = [self.visit(a) for a in node.args]
            node.keywords = [self.visit(k) for k in node.keywords]
            return node
        def visit_Subscript(self, node):
            try:
                v = eval(compile(ast.Expression(node), "<x>", "eval"), self.g, dict(self.env))
                if isinstance(v, (int, float, str, bool)) and not isinstance(v, str) or (isinstance(v, str) and len(v) <= 6):
                    return ast.copy_location(ast.Constant(v), node)
            except Exception:
                pass
            return self.generic_visit(node)
        def visit_Name(self, node):
            v = self.env.get(node.id, Ellipsis)
            if isinstance(v, (int, float)) and not isinstance(v, bool) or (isinstance(v, str) and len(v) <= 6):
                return ast.copy_location(ast.Constant(v), node)
            return node

    def target_name(node):
        t = node.targets[0] if isinstance(node, ast.Assign) else node.target
        return ast.unparse(t)

    def render(node, before, after, g):
        try:
            name = target_name(node)
            rhs = ast.unparse(Fill(before, g).visit(ast.parse(ast.unparse(node.value), mode="eval")).body)
            if isinstance(node, ast.AugAssign):
                op = ast.unparse(ast.BinOp(ast.Name("x"), node.op, ast.Name("y"))).split()[1]
                old = before.get(name)
                rhs = f"{old!r} {op} {rhs}" if isinstance(old, (int, float)) else rhs
            new = eval(name, g, dict(after))
            if not isinstance(new, (int, float, str, bool)):
                return ""
            rhs = rhs.replace("+ -", "- ").replace("- -", "+ ")
            text = f"{name} = {rhs}"
            return text if rhs == repr(new) else f"{text} = {new!r}"
        except Exception:
            return ""

    g = {"__name__": "algo"}
    real_out = sys.stdout
    sys.stdout = io.StringIO()
    exec(compile(tree, "<algo>", "exec"), g)
    steps, state, events = [], {}, [0]

    def local(frame, event, arg):
        if frame.f_code.co_filename != "<algo>":
            return local
        events[0] += 1
        if events[0] > 300000 or len(steps) > 400:
            raise RuntimeError("the code runs too long for a video: use a smaller example")
        if event not in ("line", "return"):
            return local
        st = state.setdefault(id(frame), {"line": None, "before": {}, "notes": []})
        prev, now = st["line"], snap(frame)
        if prev in assigns:
            note = render(assigns[prev], st["before"], now, g)
            if note:
                st["notes"].append(note)
        if prev in marks:
            steps.append({"line": prev, "fn": frame.f_code.co_name, "vars": now, "notes": st["notes"][-3:]})
            st["notes"] = []
        st["line"], st["before"] = (frame.f_lineno if event == "line" else None), now
        return local

    def glob(frame, event, arg):
        return local if frame.f_code.co_filename == "<algo>" else None

    sys.settrace(glob)
    try:
        result = eval(compile(call, "<call>", "eval"), g)
    finally:
        sys.settrace(None)
        sys.stdout = real_out
    print(json.dumps({"ok": True, "steps": steps, "marks": sorted(marks), "result": repr(result)[:80]}))

try:
    import sys as _s
    def _guard(event, args):
        bad = ("socket.", "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.fork", "os.remove", "os.unlink",
               "os.rmdir", "os.rename", "os.replace", "os.chmod", "os.kill", "shutil.", "ctypes.", "urllib.", "http.")
        if event.startswith(bad):
            raise PermissionError(f"not allowed in a video's code: {event}")
        if event == "open" and len(args) > 1 and isinstance(args[1], str) and any(c in args[1] for c in "wax+"):
            raise PermissionError("not allowed in a video's code: writing files")
    _s.addaudithook(_guard)
    main()
except Exception as e:
    print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}))
'''

_cache = {}


def _limits():   # in the child: at most 10 s of CPU and 1 GB of memory
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_S, TIMEOUT_S))
        resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    except (ImportError, ValueError, OSError):
        pass


def run(code, call):
    """{"ok", "steps": [{"line", "fn", "vars", "notes"}], "result"} or {"ok": False, "error"}. Remembered per (code, call)."""
    key = hashlib.sha1(json.dumps([code, call]).encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    try:
        r = subprocess.run([sys.executable, "-I", "-S", "-c", RUNNER], input=json.dumps({"code": code, "call": call}), capture_output=True,
                           text=True, timeout=TIMEOUT_S + 5, env={}, cwd="/", preexec_fn=_limits if sys.platform != "win32" else None)
        out = json.loads((r.stdout or "").strip().splitlines()[-1]) if (r.stdout or "").strip() else {"ok": False, "error": (r.stderr or "no output")[-300:]}
    except subprocess.TimeoutExpired:
        out = {"ok": False, "error": "the code ran too long (an endless loop?)"}
    except (OSError, ValueError) as e:
        out = {"ok": False, "error": str(e)[:300]}
    _cache[key] = out
    return out


def step_range(spec, total):
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", str(spec or ""))
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2) or a)
    return (a, b) if 1 <= a <= b <= total else None


def sentences(text):
    return [s.strip() for s in re.findall(r"[^.!?]+[.!?]+|[^.!?]+$", str(text or "")) if s.strip()]


def describe(step, k, view):
    """One recorded step in words, for the writer: '3: i=2, current=-2, best=1 | current = max(-3, 1 + -3) = -2'."""
    names = list(dict.fromkeys(list(view.get("pointers") or []) + list(view.get("window") or []) + list(view.get("show") or [])))
    vals = ", ".join(f"{n}={step['vars'].get(n)!r}" for n in names if n in step["vars"])
    return f"{k}: {vals}" + (f" | {'; '.join(step['notes'])}" if step.get("notes") else "")


def problems(scene, n):
    """What is wrong with a run scene ([] when it can be drawn). The real steps are listed in the message, so the writer narrates what the
    code really does."""
    p = f"scene {n}: "
    v, code = scene.get("run"), str(scene.get("code") or "")
    if not isinstance(v, dict):
        return [p + "a 'run' scene needs \"run\": {call, kind, array, pointers, window, show, steps} and its code in \"code\""]
    if "# step" not in code:
        return [p + "mark ONE line of the code with '# step' (the line whose end is one step to show, e.g. the line updating best)"]
    out = run(code, str(v.get("call") or ""))
    if not out.get("ok"):
        return [p + f"running the code with {v.get('call')!r} failed: {out.get('error')}. The code must run as written, with that call"]
    steps = out["steps"]
    if not steps:
        return [p + "the '# step' line never ran with that call: mark a line inside the loop"]
    first = steps[0]["vars"]
    arr = first.get(v.get("array"))
    if v.get("kind") == "grid":
        if not (isinstance(arr, list) and 2 <= len(arr) <= 10 and all(isinstance(r, (list, str)) and len(r) == len(arr[0]) for r in arr)):
            return [p + f"'{v.get('array')}' must be the board: a list of 2 to 10 rows of equal length, at the '# step' line"]
        if any(len(str(c)) > 1 for r in arr for c in r):
            return [p + "a grid draws one character per cell: use kind 'array' for a board of numbers, or single-character cells"]
    elif not (isinstance(arr, (list, str)) and 2 <= len(arr) <= 10):
        return [p + f"'{v.get('array')}' must be the list (or string) of 2 to 10 values drawn as cells; at the '# step' line it is {arr!r}. "
                    f"Use a smaller example"]
    for key in ("pointers", "window"):
        bad = [x for x in v.get(key) or [] if not isinstance(first.get(x), int)]
        if bad:
            return [p + f"{key} {bad} must be integer variables of the function at the '# step' line (it has: {', '.join(sorted(first))})"]
    if v.get("window") and len(v["window"]) != 2:
        return [p + "window is two variables, the first and the last lit cell: ['start', 'end']"]
    missing = [x for x in v.get("show") or [] if x not in first]
    if missing:
        return [p + f"show {missing}: no such variable at the '# step' line (it has: {', '.join(sorted(first))})"]
    rng = step_range(v.get("steps"), len(steps))
    listing = "\n".join("   " + describe(s, k, v) for k, s in enumerate(steps, 1))
    if not rng:
        return [p + f"steps {v.get('steps')!r} must be 'first-last' within 1-{len(steps)}. The code takes these {len(steps)} steps:\n{listing}"]
    count = rng[1] - rng[0] + 1
    if count > MAX_SCENE_STEPS:
        return [p + f"steps {v.get('steps')}: {count} steps, a scene shows at most {MAX_SCENE_STEPS}; show the rest in the next scene (or use a smaller example)"]
    said = sentences(scene.get("narration"))
    want = "\n".join("   " + describe(steps[k - 1], k, v) for k in range(rng[0], rng[1] + 1))
    if len(said) != count:
        return [p + f"the narration has {len(said)} sentence(s) but the scene shows {count} step(s): write exactly one sentence per step, in "
                    f"order, saying what is looked at, the calculation and the result. The steps are:\n{want}"]
    short = [k for k, s in enumerate(said, rng[0]) if len(s.split()) < MIN_WORDS]
    if short:
        return [p + f"the sentence for step {short[0]} is under {MIN_WORDS} words: say the calculation and the result. The steps are:\n{want}"]
    return []


def _note(step):
    """The calculations of a step (at most two, the last ones), skipping a line that changed nothing ('start = 3' alone)."""
    notes = [n for n in step.get("notes") or [] if n.count("=") >= 2 or "(" in n] or list(step.get("notes") or [])
    return "\n".join(notes[-2:])[:120]


def props(scene, words):
    """What Remotion draws: a trace (array) or a grid, from the recorded steps; each step starts as its sentence is said."""
    from .render import timeline
    v = scene["run"]
    out = run(scene["code"], v["call"])
    steps = out["steps"]
    a, b = step_range(v["steps"], len(steps))
    chosen = steps[a - 1:b]
    said = sentences(scene.get("narration"))
    starts, k = [], 0
    for s in said:   # the time each sentence starts: its first word in the voice's word times
        starts.append(words[k][1] if k < len(words) else (words[-1][1] if words else 0.0))
        k += len(s.split())
    times = [round(starts[i] if i < len(starts) else (starts[-1] if starts else 0) + 1.0 * i, 3) for i in range(len(chosen))]
    if times:
        times[0] = min(times[0], 0.3)
    show = list(v.get("show") or [])

    def tiles(vars_):
        return [f"{n} = {vars_[n]}" for n in show if n in vars_]

    if v.get("kind") == "grid":
        rows = ["".join(str(c) for c in r) for r in chosen[0]["vars"][v["array"]]]
        gsteps = []
        for st, t in zip(chosen, times):
            ptr = [st["vars"].get(x) for x in v.get("pointers") or []]
            cell = [ptr[:2]] if len(ptr) >= 2 and all(isinstance(x, int) for x in ptr[:2]) else []
            note = _note(st) or "  ".join(tiles(st["vars"]))[:80]
            gsteps.append({"t": t, "active": cell, "found": [], "out": [], "marks": [], "pluses": [], "note": note})
        return {"layout": "grid", "grid": {"title": str(scene.get("on_screen") or "")[:60], "rows": rows, "legend": [], "colors": {}, "blocked": [],
                                            "steps": gsteps}}
    tsteps, cells0 = [], [str(c) for c in chosen[0]["vars"][v["array"]]]
    for st, t in zip(chosen, times):
        vars_ = st["vars"]
        arr = [str(c) for c in vars_.get(v["array"]) or []]
        active = []
        if v.get("window") and all(isinstance(vars_.get(x), int) for x in v["window"]):
            lo, hi = sorted(vars_[x] for x in v["window"])
            active = [i for i in range(lo, hi + 1) if 0 <= i < len(arr)]
        ptrs = [{"name": x, "at": vars_[x]} for x in v.get("pointers") or [] if isinstance(vars_.get(x), int) and 0 <= vars_[x] < len(arr)]
        if not active:
            active = [q["at"] for q in ptrs]
        tsteps.append({"t": t, "pointers": ptrs, "active": active, "out": [], "found": [], "note": _note(st),
                       "memo": tiles(vars_), **({"cells": arr} if arr != cells0 else {})})
    return {"layout": "trace", "cells": cells0, "steps": tsteps}
