"""A real graph: the `graph` scene, for every problem whose data is nodes joined by edges (a network, a map of cities, courses and their
prerequisites, a tree drawn as nodes and links, BFS, DFS, Dijkstra, topological order, union-find, cycles, connected components).
A row of cells or a board cannot show "joined to"; this draws the nodes and edges as they are and walks them while the voice speaks.

The writer gives the nodes, the edges (with weights when the problem has them) and the moves, one step per beat of the narration. A step
names the node being worked on (current), the nodes already done (visited), the nodes waiting their turn (frontier: a queue or a stack),
the answer (found), nodes ruled out (out), the edges being followed (edges) and a short label under a node ("B=4": a distance, an order).
The app places the nodes itself, in layers from the first node, so the picture is always readable, and it refuses an edge or a step that
names a node the graph does not have, so the picture is always true.
"""
import re
from collections import deque

MIN_NODES, MAX_NODES = 2, 12
MAX_EDGES = 24
MAX_STEPS = 12
NAME = re.compile(r"^[A-Za-z0-9]{1,4}$")
EDGE = re.compile(r"^\s*([A-Za-z0-9]{1,4})\s*(?:-|->|>)\s*([A-Za-z0-9]{1,4})\s*(?::\s*(-?\d{1,5}))?\s*$")
LABEL = re.compile(r"^\s*([A-Za-z0-9]{1,4})\s*=\s*(.{1,8}?)\s*$")

STEP = {
    "type": "object",
    "properties": {
        "say": {"type": "string", "description": "two or three words of the narration, said just as this step happens"},
        "current": {"type": "array", "items": {"type": "string"}, "maxItems": 2, "description": "the node being worked on now: ['B'] ([] for none)"},
        "visited": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_NODES, "description": "every node already done, so far: ['A', 'B']"},
        "frontier": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_NODES,
                     "description": "nodes waiting their turn, in order (the queue of a BFS, the stack of a DFS): ['C', 'D']"},
        "found": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_NODES, "description": "nodes that are the answer (the path found, the target)"},
        "out": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_NODES, "description": "nodes ruled out or not reachable now"},
        "edges": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_EDGES,
                  "description": "edges lit now, written as in graph.edges without the weight: 'A-B' (the edge being followed, or the path so far)"},
        "labels": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_NODES,
                   "description": "a short value shown under a node: 'B=4' (a distance, an order number; at most 8 characters)"},
        "note": {"type": "string", "description": "what this step shows, at most 60 characters: 'queue: C, D'"},
    },
    "required": ["say", "current", "visited", "frontier", "found", "out", "edges", "labels", "note"],
    "additionalProperties": False,
}
GRAPH = {
    "type": "object",
    "description": "a `graph` scene only: real nodes and edges and the moves on them, drawn by the app",
    "properties": {
        "title": {"type": "string", "description": "the small heading over the graph, at most 40 characters"},
        "nodes": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_NODES,
                  "description": "the nodes, 2 to 12 short names (1 to 4 letters or digits): ['A', 'B', 'C']. Copy the problem's example; the first is the start"},
        "edges": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_EDGES,
                  "description": "the edges, 'A-B', or 'A-B:4' with its weight. With directed true, 'A-B' goes from A to B. Copy the problem's example exactly"},
        "directed": {"type": "boolean", "description": "true when the edges have a direction (prerequisites, one-way roads)"},
        "steps": {"type": "array", "items": STEP, "maxItems": MAX_STEPS, "description": "the moves, in the order the voice says them"},
    },
    "required": ["title", "nodes", "edges", "directed", "steps"],
    "additionalProperties": False,
}
START_S, PER_STEP_MIN, STEP_GAP = 0.6, 1.4, 0.9


def parse_edges(v):
    """[(a, b, weight or None)] of the well-formed edges."""
    out = []
    for e in v.get("edges") or []:
        m = EDGE.match(str(e))
        if m:
            out.append((m.group(1), m.group(2), int(m.group(3)) if m.group(3) is not None else None))
    return out


def _edge_index(v):
    """{(a, b): index}; an undirected edge answers to both directions."""
    idx = {}
    for i, (a, b, _w) in enumerate(parse_edges(v)):
        idx.setdefault((a, b), i)
        if not v.get("directed"):
            idx.setdefault((b, a), i)
    return idx


def problems(v, n):
    p = f"scene {n}: "
    if not isinstance(v, dict):
        return [p + "a 'graph' scene needs its graph in \"graph\": {title, nodes, edges, directed, steps}"]
    nodes = [str(x).strip() for x in v.get("nodes") or []]
    if not MIN_NODES <= len(nodes) <= MAX_NODES:
        return [p + f"graph.nodes: {MIN_NODES} to {MAX_NODES} nodes (pick a smaller example if the problem's is bigger)"]
    bad = [x for x in nodes if not NAME.match(x)]
    if bad:
        return [p + f"graph.nodes are short names, 1 to 4 letters or digits, not {bad[:2]}"]
    if len(set(nodes)) != len(nodes):
        return [p + f"graph.nodes must each appear once: {nodes}"]
    have = set(nodes)
    out = []
    raw = v.get("edges") or []
    if not raw:
        out.append(p + "graph.edges: at least one edge ('A-B'), or this is not a graph")
    if len(raw) > MAX_EDGES:
        out.append(p + f"graph.edges: at most {MAX_EDGES} edges")
    seen = set()
    for e in raw:
        m = EDGE.match(str(e))
        if not m:
            out.append(p + f"edge '{e}' must be 'A-B' or 'A-B:4' (with its weight)")
            continue
        a, b = m.group(1), m.group(2)
        if a not in have or b not in have:
            out.append(p + f"edge '{e}' joins {a if a not in have else b}, which is not in graph.nodes {nodes}")
        elif a == b:
            out.append(p + f"edge '{e}' joins a node to itself: leave it out")
        key = (a, b) if v.get("directed") else tuple(sorted((a, b)))
        if key in seen:
            out.append(p + f"edge '{e}' is listed twice")
        seen.add(key)
    weights = [w for _a, _b, w in parse_edges(v)]
    if any(w is not None for w in weights) and any(w is None for w in weights):
        out.append(p + "graph.edges: give every edge its weight ('A-B:4') or none of them")
    steps = v.get("steps") or []
    if not steps:
        out.append(p + "graph.steps: at least one step, so something happens on the graph as the voice speaks")
    idx = _edge_index(v)
    for k, st in enumerate(steps, 1):
        for key in ("current", "visited", "frontier", "found", "out"):
            unknown = [x for x in st.get(key) or [] if str(x).strip() not in have]
            if unknown:
                out.append(p + f"step {k}: {key} names {unknown[0]!r}, which is not in graph.nodes {nodes}")
        for e in st.get("edges") or []:
            m = EDGE.match(str(e))
            if not m or (m.group(1), m.group(2)) not in idx:
                out.append(p + f"step {k}: edge '{e}' is not one of graph.edges (write it as listed there, 'A-B')")
        for lab in st.get("labels") or []:
            m = LABEL.match(str(lab))
            if not m or m.group(1) not in have:
                out.append(p + f"step {k}: label '{lab}' must be 'node=value' (at most 8 characters) on a node of the graph")
    return out


def layout(v):
    """{node: (x, y)} in 0..1: layers by distance from the first node (BFS, edges both ways), each layer ordered to sit under the nodes that
    reach it, so most edges run down and few cross. A node the first cannot reach starts its own layers below."""
    nodes = [str(x).strip() for x in v.get("nodes") or []]
    nbr = {x: [] for x in nodes}
    for a, b, _w in parse_edges(v):
        if a in nbr and b in nbr and a != b:
            nbr[a].append(b)
            nbr[b].append(a)
    depth, order = {}, []
    base = 0
    for root in nodes:
        if root in depth:
            continue
        depth[root] = base
        q = deque([root])
        while q:
            x = q.popleft()
            order.append(x)
            for y in nbr[x]:
                if y not in depth:
                    depth[y] = depth[x] + 1
                    q.append(y)
        base = max(depth.values()) + 1
    layers = {}
    for x in order:
        layers.setdefault(depth[x], []).append(x)
    pos = {}
    nl = max(layers) + 1 if layers else 1
    for d in sorted(layers):
        row = layers[d]
        if d > 0:   # sit under the parents: the mean x of the neighbours already placed
            row.sort(key=lambda x: (sum(pos[y][0] for y in nbr[x] if y in pos) / max(1, sum(1 for y in nbr[x] if y in pos))
                                    if any(y in pos for y in nbr[x]) else 0.5, nodes.index(x)))
        for i, x in enumerate(row):
            pos[x] = ((i + 0.5) / len(row), d / (nl - 1) if nl > 1 else 0.5)   # the full width and height: long edges, room for weights
    return pos


def min_seconds(v):
    return START_S + PER_STEP_MIN * len(v.get("steps") or [])


def props(v, when):
    """What Remotion draws. when(say, after) -> the time the words are said (render/remotion.py)."""
    nodes = [str(x).strip() for x in v.get("nodes") or []]
    pos = layout(v)
    idx = _edge_index(v)
    clean = lambda xs: [str(x).strip() for x in xs or [] if str(x).strip() in pos]
    steps, said = [], -1.0
    for st in v.get("steps") or []:
        t = when(st.get("say"), max(said, 0.0))
        if t <= said:   # a step never lands on the moment of the one before it (it would never be seen): just after it
            t = said + STEP_GAP
        said = t
        lit = []
        for e in st.get("edges") or []:
            m = EDGE.match(str(e))
            if m and (m.group(1), m.group(2)) in idx and idx[(m.group(1), m.group(2))] not in lit:
                lit.append(idx[(m.group(1), m.group(2))])
        labels = {}
        for lab in st.get("labels") or []:
            m = LABEL.match(str(lab))
            if m and m.group(1) in pos:
                labels[m.group(1)] = m.group(2)
        steps.append({"t": round(t, 3), "current": clean(st.get("current")), "visited": clean(st.get("visited")),
                      "frontier": clean(st.get("frontier")), "found": clean(st.get("found")), "out": clean(st.get("out")),
                      "edges": lit, "labels": labels, "note": str(st.get("note") or "")[:80]})
    return {"title": str(v.get("title") or "")[:60], "directed": bool(v.get("directed")),
            "nodes": [{"name": x, "x": round(pos[x][0], 4), "y": round(pos[x][1], 4)} for x in nodes],
            "edges": [{"a": a, "b": b, "w": w} for a, b, w in parse_edges(v)], "steps": steps}
