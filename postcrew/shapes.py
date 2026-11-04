"""The data shape of a problem, and the picture that can show it. A video teaches an algorithm by drawing its data moving; a problem whose
data the renderer cannot draw gets squeezed into the nearest picture (a grid flattened into one row, a tree drawn as a list) and the video is
wrong however well it is written. So:

  * the shape is named first: by the Reader from the problem's own material (most reliable), else from the words of the topic;
  * a shape the renderer can draw must be drawn with its picture (SCENES), in at least two scenes, on the problem's own example;
  * a shape it cannot draw yet (UNDRAWABLE), named by the Reader, stops the run before any writing: no money is spent on a video that would
    be wrong. A shape guessed from words only warns (the guess may be wrong; the Editor and the Quality Director still judge the result).
"""
import re

# shape -> the layouts that draw it
SCENES = {"array": ("trace", "codeviz"), "string": ("trace", "codeviz"), "grid": ("grid",), "number_table": ("codeviz", "grid"),
          "ways": ("paths", "codeviz")}
UNDRAWABLE = {"tree": "a tree", "graph": "a graph (nodes and edges)", "linked_list": "a linked list", "stack_queue": "a stack or a queue",
              "intervals": "intervals on a number line"}
SHAPES = list(SCENES) + list(UNDRAWABLE) + ["other"]
LABEL = {"array": "an array (one row of values)", "string": "a string", "grid": "a grid (rows and columns)",
         "number_table": "a table of numbers (a DP table)", "ways": "counting ways (a staircase)", "other": "no particular data", **UNDRAWABLE}

# the words that give a shape away, strongest first (the first match wins)
WORDS = [
    ("grid", r"\b(grid|matrix|board|maze|rows? and columns?|\d+\s*[x×]\s*\d+ (?:grid|board)|n\s*[x×]\s*m\b|2-?d array|two-dimensional|islands?|chessboard|n-?queens|flood fill|word search)\b"),
    ("tree", r"\b(binary tree|bst|binary search tree|trie|heap|segment tree|tree traversal|inorder|preorder|postorder|lowest common ancestor|subtree|root node|leaf nodes?)\b"),
    ("graph", r"\b(graph|vertices|vertex|edges?\b.*\bnodes?|dijkstra|bfs|dfs|topological|shortest path|spanning tree|union[- ]find|cycle detection|connected components?)\b"),
    ("linked_list", r"\b(linked list|next pointer|head node|singly|doubly)\b"),
    ("stack_queue", r"\b(stack|queue|deque|monotonic stack|push and pop|parenthes[ie]s|brackets? match)\b"),
    ("intervals", r"\b(intervals?|meeting rooms?|merge overlapping|number line|ranges? overlap)\b"),
    ("number_table", r"\b(dp table|knapsack|longest common subsequence|edit distance|lcs)\b"),
    ("ways", r"\b(how many (?:different )?ways|number of ways|climbing stairs|staircase)\b"),
    ("string", r"\b(string|substring|palindrome|anagram|characters?)\b"),
    ("array", r"\b(array|list of (?:integers|numbers)|two pointers?|sliding window|subarray|sorted|binary search|prefix sum)\b"),
]


def from_words(text):
    for shape, rx in WORDS:
        if re.search(rx, text or "", re.I):
            return shape
    return "other"


def of(ctx):
    """(shape, source): "reader" when the Reader named it from the problem's files, "words" when guessed from the topic, or ("other", "")."""
    topic = ctx.outputs.get("topic") or {}
    plan = topic.get("owner_plan") or {}
    if plan.get("shape") in SHAPES:
        return plan["shape"], "reader"
    shape = from_words(" ".join([plan.get("statement", ""), plan.get("context", ""), topic.get("topic", ""), topic.get("angle", "")]))
    return shape, ("words" if shape != "other" else "")


def stop_reason(shape, source):
    """Why a run must stop before writing (a shape the renderer cannot draw, named from the problem's files), or ''."""
    if source == "reader" and shape in UNDRAWABLE:
        return (f"this problem is about {UNDRAWABLE[shape]}, and the video cannot draw {UNDRAWABLE[shape]} yet: a video squeezed into "
                f"another picture would teach it wrong, so nothing was written and nothing was spent on it. Pick another problem, or ask for "
                f"a {shape.replace('_', ' ')} scene to be added")
    return ""


def scene_problems(ctx, script):
    """The script draws its problem with the right picture, in at least two scenes."""
    shape, source = of(ctx)
    want = SCENES.get(shape)
    if not want:
        return []
    scenes = script.get("scenes") or []
    got = [s for s in scenes if s.get("layout") in want]
    if len(got) >= 2:
        return []
    extra = (" A 'trace' is a single row and cannot show above or below." if shape == "grid" else "")
    return [f"this problem is about {LABEL[shape]}, so it must be DRAWN as one: use {' or '.join(repr(w) for w in want)} scenes (at least two: "
            f"the problem's example, then the idea step by step on it; the mistake too). You have {len(got)}.{extra}"]


# ---------- the problem's own example ----------
def sample_boards(statement):
    """The sample grids in the Reader's examples: [[row, ...], ...] (rows of one character per cell, all the same length)."""
    out = []
    for e in (statement or {}).get("examples") or []:
        lines = [ln.strip() for ln in str(e.get("input", "")).splitlines()]
        rows = [ln for ln in lines if re.fullmatch(r"\S{2,}", ln) and not re.fullmatch(r"[\d\s]+", ln)]
        if len(rows) >= 2 and len({len(r) for r in rows}) == 1:
            out.append(rows)
    return out


def sample_arrays(statement):
    """The sample arrays in the Reader's examples: [["2", "7", "11", "15"], ...]."""
    out = []
    for e in (statement or {}).get("examples") or []:
        for m in re.finditer(r"\[([^\[\]]{1,200})\]", str(e.get("input", ""))):
            vals = [v.strip().strip("'\"") for v in m.group(1).split(",") if v.strip()]
            if 2 <= len(vals) <= 10:
                out.append(vals)
    return out


def example_problems(ctx, script, statement):
    """When the problem came from files: the video works the problem's OWN example (a sample board or array copied exactly), not one it made up.
    The idea may also be shown on smaller cases; at least one picture must be the real sample."""
    if not statement:
        return []
    shape = of(ctx)[0]
    scenes = script.get("scenes") or []
    if shape == "grid":
        boards = sample_boards(statement)
        if not boards:
            return []
        drawn = [list((s.get("grid") or {}).get("rows") or []) for s in scenes if s.get("layout") == "grid"]
        if any(d == b for d in drawn for b in boards):
            return []
        show = "\n".join("  " + " / ".join(b) for b in boards)
        return [f"no grid scene shows the problem's own sample board. Copy one exactly into a grid scene's rows (one string per row):\n{show}"]
    if shape in ("array", "string"):
        arrays = sample_arrays(statement)
        if not arrays:
            return []
        drawn = [[str(c) for c in s.get("cells") or []] for s in scenes if s.get("layout") == "trace"]
        if any(d == a for d in drawn for a in arrays):
            return []
        return [f"no trace scene works the problem's own sample input. Put one into a trace scene's cells exactly: "
                + "; ".join(str(a) for a in arrays[:2])]
    return []
