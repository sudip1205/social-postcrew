"""A real staircase with an arrow for every way up: the `paths` scene, the visual explanation that comes BEFORE the code.

The writer names the staircase (how many steps, which hops are allowed) and the app finds every way to the top, then draws each one as a child would
see it: a little figure hops from step to step along an arrow while the "ways found" counter climbs and the way is written down ("1 + 2 + 2"). Because
the app enumerates the ways itself, the count on screen is always right (2 steps: 2 ways, 3 steps: 3, 4 steps: 5, 5 steps: 8).
"""

KINDS = ("stairs",)
MAX_PATHS = 21
START_S = 0.8
TAIL_S = 1.2
PER_MIN, PER_MAX = 0.9, 1.8

PATHS = {
    "type": "object",
    "description": "a `paths` scene only: a drawn staircase and every way up it, found and animated by the app",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "title": {"type": "string", "description": "the small heading over the picture, at most 40 characters: '3 steps, how many ways?'"},
        "n": {"type": "integer", "description": "how many steps the staircase has: 1 to 6"},
        "moves": {"type": "array", "items": {"type": "integer"}, "maxItems": 3, "description": "the hops allowed, in steps: [1, 2] is one step or two at a time"},
    },
    "required": ["kind", "title", "n", "moves"],
    "additionalProperties": False,
}


def enumerate_paths(n, moves):
    """Every way to climb n steps with these hops, shortest hops first: [[1, 1, 2], [1, 2, 1], ...]."""
    out = []

    def go(at, hops):
        if at == n:
            out.append(list(hops))
            return
        for m in sorted(moves):
            if at + m <= n:
                go(at + m, hops + [m])
    go(0, [])
    return out


def problems(v, n):
    p = f"scene {n}: "
    if not isinstance(v, dict) or v.get("kind") not in KINDS:
        return [p + "a 'paths' scene needs its 'paths' (kind stairs, title, n, moves)"]
    out = []
    if not 3 <= len(str(v.get("title") or "").strip()) <= 40:
        out.append(p + "paths.title is 3 to 40 characters")
    moves = v.get("moves") or []
    if not 1 <= len(moves) <= 3 or any(not isinstance(m, int) or m < 1 or m > 4 for m in moves) or len(set(moves)) != len(moves):
        return out + [p + "paths.moves lists the hops allowed, each 1 to 4 steps, no repeats ([1, 2])"]
    if not isinstance(v.get("n"), int) or not 1 <= v["n"] <= 6:
        return out + [p + "paths.n is the number of steps, 1 to 6 (it has to stay small enough to see every way)"]
    if len(enumerate_paths(v["n"], moves)) > MAX_PATHS:
        out.append(p + f"that staircase has more than {MAX_PATHS} ways up: use fewer steps or fewer hops")
    return out


def min_seconds(v):
    return START_S + 1.1 * len(enumerate_paths(v["n"], v["moves"])) + TAIL_S


def props(v, seconds):
    paths = enumerate_paths(int(v["n"]), [int(m) for m in v["moves"]])
    avail = max(1.0, seconds - START_S - TAIL_S)
    per = max(PER_MIN, min(PER_MAX, avail / max(1, len(paths))))
    return {"kind": "stairs", "title": str(v["title"]), "n": int(v["n"]), "moves": [int(m) for m in v["moves"]], "per": round(per, 3),
            "paths": [{"hops": p, "label": " + ".join(str(h) for h in p), "t": round(START_S + k * per, 3)} for k, p in enumerate(paths)]}
