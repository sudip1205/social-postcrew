"""Algorithm library for the Monday animation post.

Each Tracer holds the real Java source shown in the video and a trace(): the
step-by-step frames (which Java line is active, what to say, what the data looks
like). tests/ compile and run the Java and compare it with the trace's result, so
the code on screen is verified, not just drawn.

Add an algorithm: write a generator below, register it in TRACERS, add a test.
"""
from dataclasses import dataclass
from typing import Callable, Optional


# ---------- frame builders ----------
def P(*pairs):
    """pointers: (position, label) pairs -> {position: [labels]}"""
    out = {}
    for pos, label in pairs:
        if pos is not None:
            out.setdefault(pos, []).append(label)
    return out


class Bars:
    """Bars whose identity (id) survives swaps, so the renderer can slide them."""

    def __init__(self, values):
        self.val = dict(enumerate(values))
        self.order = list(range(len(values)))
        self.sorted = set()

    def arr(self):
        return [self.val[i] for i in self.order]

    def swap(self, i, j):
        self.order[i], self.order[j] = self.order[j], self.order[i]

    def snap(self, line, caption, dur, rng=None, marks=None, pointers=None, aux=None, range_label="",
             sorted_pos=()):
        marks = marks or {}
        roles = {}
        for pos, i in enumerate(self.order):
            if i in marks:
                roles[i] = marks[i]
            elif i in self.sorted or pos in sorted_pos:
                roles[i] = "sorted"
            elif rng and not (rng[0] <= pos <= rng[1]):
                roles[i] = "dim"
            else:
                roles[i] = "bar"
        return {"line": line, "caption": caption, "dur": dur, "viz": {
            "kind": "bars", "order": list(self.order), "val": dict(self.val), "roles": roles,
            "range": rng, "range_label": range_label, "pointers": pointers or {},
            "aux": None if aux is None else [(p, None if i is None else self.val[i]) for p, i in aux]}}


NODES = "ABCDEFG"
POS = {"A": (130, 400), "B": (350, 310), "C": (350, 500), "D": (600, 290), "E": (600, 410),
       "F": (600, 530), "G": (850, 410)}
EDGES = [("A", "B"), ("A", "C"), ("B", "D"), ("B", "E"), ("C", "E"), ("C", "F"), ("E", "G"), ("F", "G")]
ADJ = {n: sorted([b for a, b in EDGES if a == n] + [a for a, b in EDGES if b == n]) for n in NODES}


def graph_frame(line, caption, dur, roles, labels, chips_label, chips, edge=None):
    return {"line": line, "caption": caption, "dur": dur, "viz": {
        "kind": "graph", "pos": POS, "edges": EDGES, "roles": dict(roles), "labels": dict(labels),
        "chips_label": chips_label, "chips": list(chips), "active_edge": edge}}


# ---------- Quick sort ----------
QUICK_JAVA = """static void quickSort(int[] a, int lo, int hi) {
    if (lo >= hi) return;
    int pivot = a[hi];
    int i = lo;
    for (int j = lo; j < hi; j++) {
        if (a[j] < pivot) {
            swap(a, i, j);
            i++;
        }
    }
    swap(a, i, hi);
    quickSort(a, lo, i - 1);
    quickSort(a, i + 1, hi);
}"""


def _quicksort(out):
    B = Bars([38, 27, 43, 3, 9, 10, 55, 19, 64, 82])
    first = [True]
    yield B.snap(None, "Unsorted array. Let's sort it with quick sort.", 2.0)

    def qs(lo, hi):
        if lo > hi:
            return
        rng = (lo, hi)
        if lo == hi:
            B.sorted.add(B.order[lo])
            yield B.snap(2, f"a[{lo}..{hi}] has one element: already in place", 0.7, rng)
            return
        pid = B.order[hi]
        pivot = B.val[pid]
        i = lo
        label = f"working on a[{lo}..{hi}]"
        yield B.snap(3, f"Pick the last element as the pivot: {pivot}", 1.2, rng, {pid: "pivot"},
                     P((hi, "pivot")), range_label=label)
        if first[0]:
            first[0] = False
            yield B.snap(4, "i marks where the next smaller value will go", 1.1, rng, {pid: "pivot"},
                         P((hi, "pivot"), (i, "i")), range_label=label)
        for j in range(lo, hi):
            jid = B.order[j]
            v = B.val[jid]
            small = v < pivot
            yield B.snap(6, f"Is {v} < {pivot}? " + ("Yes: move it to the left side" if small else "No: leave it"),
                         0.75 if small else 0.55, rng, {pid: "pivot", jid: "cmp"},
                         P((hi, "pivot"), (i, "i"), (j, "j")), range_label=label)
            if small:
                if i != j:
                    iid = B.order[i]
                    B.swap(i, j)
                    yield B.snap(7, f"Swap a[{i}] and a[{j}]", 0.9, rng, {pid: "pivot", jid: "swap", iid: "swap"},
                                 P((hi, "pivot"), (i, "i")), range_label=label)
                i += 1
        if i != hi:
            B.swap(i, hi)
        B.sorted.add(pid)
        yield B.snap(11, f"Drop the pivot into its final spot: index {i}", 1.3, rng, None,
                     P((i, "done")), range_label=label)
        if i - 1 - lo >= 1:
            yield B.snap(12, f"Now sort the left part: a[{lo}..{i - 1}]", 0.9, (lo, i - 1))
        yield from qs(lo, i - 1)
        if hi - (i + 1) >= 1:
            yield B.snap(13, f"Now sort the right part: a[{i + 1}..{hi}]", 0.9, (i + 1, hi))
        yield from qs(i + 1, hi)

    yield from qs(0, 9)
    B.sorted = set(B.order)
    out["result"] = str(B.arr())
    yield B.snap(None, "Sorted! Average time O(n log n).", 3.0)


# ---------- Merge sort ----------
MERGE_JAVA = """static void mergeSort(int[] a, int[] tmp, int lo, int hi) {
    if (hi - lo < 1) return;
    int mid = (lo + hi) / 2;
    mergeSort(a, tmp, lo, mid);
    mergeSort(a, tmp, mid + 1, hi);
    int i = lo, j = mid + 1, k = lo;
    while (i <= mid && j <= hi) {
        tmp[k++] = a[i] <= a[j] ? a[i++] : a[j++];
    }
    while (i <= mid) tmp[k++] = a[i++];
    while (j <= hi) tmp[k++] = a[j++];
    for (k = lo; k <= hi; k++) a[k] = tmp[k];
}"""


def _mergesort(out):
    B = Bars([38, 27, 43, 3, 9, 82, 10, 55])
    yield B.snap(None, "Unsorted array. Let's sort it with merge sort.", 2.0, aux=[])

    def ms(lo, hi):
        if hi - lo < 1:
            return
        mid = (lo + hi) // 2
        yield B.snap(3, f"Split a[{lo}..{hi}] in the middle (mid = {mid})", 1.0, (lo, hi), None,
                     P((mid, "mid")), [], f"splitting a[{lo}..{hi}]")
        yield from ms(lo, mid)
        yield from ms(mid + 1, hi)
        left, right = B.order[lo:mid + 1], B.order[mid + 1:hi + 1]
        i = j = 0
        tmp = []
        rl = f"merging a[{lo}..{hi}]"

        def ptrs():
            return P((lo + i if i < len(left) else None, "i"), (mid + 1 + j if j < len(right) else None, "j"),
                     (lo + len(tmp) if lo + len(tmp) <= hi else None, "k"))

        yield B.snap(6, f"Merge the sorted halves a[{lo}..{mid}] and a[{mid + 1}..{hi}]", 1.0, (lo, hi), None,
                     ptrs(), [], rl)
        while i < len(left) and j < len(right):
            li, rj = left[i], right[j]
            pick = li if B.val[li] <= B.val[rj] else rj
            tmp.append((lo + len(tmp), pick))
            yield B.snap(8, f"Compare {B.val[li]} and {B.val[rj]}: take {B.val[pick]} into tmp[{lo + len(tmp) - 1}]",
                         0.95, (lo, hi), {li: "cmp", rj: "cmp", pick: "mid"}, ptrs_after(lo, i, j, left, right, mid, tmp, hi, pick == li),
                         tmp, rl)
            if pick == li:
                i += 1
            else:
                j += 1
        if i < len(left):
            rest = left[i:]
            line, side = 10, "left"
        else:
            rest = right[j:]
            line, side = 11, "right"
        if rest:
            for r in rest:
                tmp.append((lo + len(tmp), r))
            yield B.snap(line, f"The other side is empty: copy the rest of the {side} side", 0.95, (lo, hi),
                         {r: "mid" for r in rest}, None, tmp, rl)
        new = [i_ for _, i_ in tmp]
        B.order[lo:hi + 1] = new
        B.sorted |= set(new)
        yield B.snap(12, f"Copy tmp back: a[{lo}..{hi}] is now sorted", 1.3, (lo, hi), None, None, [], rl)

    yield from ms(0, 7)
    B.sorted = set(B.order)
    out["result"] = str(B.arr())
    yield B.snap(None, "Sorted! Always O(n log n), and it is stable.", 3.0, aux=[])


def ptrs_after(lo, i, j, left, right, mid, tmp, hi, took_left):
    ni, nj = i + (1 if took_left else 0), j + (0 if took_left else 1)
    return P((lo + ni if ni < len(left) else None, "i"), (mid + 1 + nj if nj < len(right) else None, "j"),
             (lo + len(tmp) if lo + len(tmp) <= hi else None, "k"))


# ---------- Binary search ----------
BINARY_JAVA = """static int binarySearch(int[] a, int target) {
    int lo = 0, hi = a.length - 1;
    while (lo <= hi) {
        int mid = lo + (hi - lo) / 2;
        if (a[mid] == target) return mid;
        if (a[mid] < target) lo = mid + 1;
        else hi = mid - 1;
    }
    return -1;
}"""


def _binarysearch(out):
    vals = [3, 8, 12, 17, 21, 25, 31, 38, 42, 57, 63, 79]
    B = Bars(vals)
    results = []
    yield B.snap(None, "A sorted array of 12 numbers. Find 57, then 40.", 2.0)
    for target in (57, 40):
        B.sorted.clear()
        lo, hi = 0, len(vals) - 1
        label = f"searching for {target}"
        yield B.snap(2, f"Search for {target}: lo = {lo}, hi = {hi}", 1.3, (lo, hi), None,
                     P((lo, "lo"), (hi, "hi")), range_label=label)
        found = -1
        while lo <= hi:
            mid = lo + (hi - lo) // 2
            v = vals[mid]
            yield B.snap(4, f"mid = {mid}, a[mid] = {v}", 1.2, (lo, hi), {mid: "mid"},
                         P((lo, "lo"), (hi, "hi"), (mid, "mid")), range_label=label)
            if v == target:
                found = mid
                B.sorted.add(mid)
                yield B.snap(5, f"{v} == {target}: found it at index {mid}", 2.2, (lo, hi), None,
                             P((mid, "found")), range_label=label)
                break
            if v < target:
                lo = mid + 1
                yield B.snap(6, f"{v} < {target}: discard the left half, lo = {lo}", 1.3, (lo, hi), None,
                             P((lo, "lo"), (hi, "hi")), range_label=label)
            else:
                hi = mid - 1
                yield B.snap(7, f"{v} > {target}: discard the right half, hi = {hi}", 1.3, (lo, hi), None,
                             P((lo, "lo"), (hi, "hi")), range_label=label)
        if found < 0:
            yield B.snap(9, f"lo > hi: nothing left, {target} is not here. Return -1", 2.2, (lo, hi), None, None,
                         range_label=label)
        results.append(found)
    out["result"] = " ".join(map(str, results))
    yield B.snap(None, "Each step halves the search space: O(log n).", 3.0)


# ---------- Bubble sort ----------
BUBBLE_JAVA = """static void bubbleSort(int[] a) {
    for (int pass = 0; pass < a.length - 1; pass++) {
        boolean swapped = false;
        for (int j = 0; j < a.length - 1 - pass; j++) {
            if (a[j] > a[j + 1]) {
                swap(a, j, j + 1);
                swapped = true;
            }
        }
        if (!swapped) break;
    }
}"""


def _bubblesort(out):
    B = Bars([6, 3, 8, 2, 9, 1, 5])
    n = len(B.order)
    yield B.snap(None, "Unsorted array. Let's sort it with bubble sort.", 2.0)
    for p in range(n - 1):
        swapped = False
        for j in range(n - 1 - p):
            l, r = B.order[j], B.order[j + 1]
            vl, vr = B.val[l], B.val[r]
            need = vl > vr
            yield B.snap(5, f"Is {vl} > {vr}? " + ("Yes: swap them" if need else "No: leave them"),
                         0.6, None, {l: "cmp", r: "cmp"}, P((j, "j")))
            if need:
                B.swap(j, j + 1)
                swapped = True
                yield B.snap(6, f"Swap {vl} and {vr}", 0.85, None, {l: "swap", r: "swap"}, P((j + 1, "j")))
        last = B.order[n - 1 - p]
        B.sorted.add(last)
        if swapped:
            yield B.snap(10, f"Pass {p + 1} done: {B.val[last]} is in its final place", 0.9)
        else:
            B.sorted = set(B.order)
            yield B.snap(10, "No swaps in this pass: the array is sorted. Stop early.", 1.4)
            break
    B.sorted = set(B.order)
    out["result"] = str(B.arr())
    yield B.snap(None, "Sorted! Simple, but O(n²) comparisons.", 3.0)


# ---------- Insertion sort ----------
INSERTION_JAVA = """static void insertionSort(int[] a) {
    for (int i = 1; i < a.length; i++) {
        int key = a[i];
        int j = i - 1;
        while (j >= 0 && a[j] > key) {
            a[j + 1] = a[j];
            j--;
        }
        a[j + 1] = key;
    }
}"""


def _insertionsort(out):
    B = Bars([7, 3, 9, 1, 6, 2, 8, 4])
    n = len(B.order)
    yield B.snap(None, "Unsorted array. The left part will grow sorted.", 2.0, sorted_pos={0})
    for i in range(1, n):
        kid = B.order[i]
        key = B.val[kid]
        pos = i
        yield B.snap(3, f"Take key = {key} out of the unsorted part", 1.0, None, {kid: "mid"},
                     P((i, "key")), sorted_pos=set(range(i)))
        while pos > 0 and B.val[B.order[pos - 1]] > key:
            bigger = B.val[B.order[pos - 1]]
            B.swap(pos, pos - 1)
            pos -= 1
            yield B.snap(6, f"{bigger} > {key}: shift {bigger} one step right", 0.8, None, {kid: "mid"},
                         P((pos, "key")), sorted_pos=set(range(i + 1)))
        msg = f"Insert {key} at index {pos}" if pos != i else f"{key} is already in the right place"
        yield B.snap(9, msg, 0.9, None, {kid: "mid"}, P((pos, "key")), sorted_pos=set(range(i + 1)))
    B.sorted = set(B.order)
    out["result"] = str(B.arr())
    yield B.snap(None, "Sorted! Fast on small or nearly sorted data.", 3.0)


# ---------- BFS ----------
BFS_JAVA = """static int[] bfs(List<List<Integer>> g, int src) {
    int[] dist = new int[g.size()];
    Arrays.fill(dist, -1);
    Queue<Integer> q = new ArrayDeque<>();
    dist[src] = 0;
    q.add(src);
    while (!q.isEmpty()) {
        int u = q.poll();
        for (int v : g.get(u)) {
            if (dist[v] == -1) {
                dist[v] = dist[u] + 1;
                q.add(v);
            }
        }
    }
    return dist;
}"""


def _bfs(out):
    dist = {n: -1 for n in NODES}
    roles = {n: "unseen" for n in NODES}
    labels = {}
    q = []
    yield graph_frame(None, "Find the fewest hops from A to every node.", 2.0, roles, labels, "Queue", q)
    dist["A"], roles["A"], labels["A"] = 0, "queued", "dist 0"
    q.append("A")
    yield graph_frame(5, "Start: dist[A] = 0, put A in the queue", 1.2, roles, labels, "Queue", q)
    while q:
        u = q.pop(0)
        roles[u] = "current"
        yield graph_frame(8, f"Take {u} from the queue", 1.0, roles, labels, "Queue", q)
        for v in ADJ[u]:
            if dist[v] == -1:
                dist[v] = dist[u] + 1
                roles[v], labels[v] = "queued", f"dist {dist[v]}"
                q.append(v)
                yield graph_frame(11, f"{v} is new: dist[{v}] = {dist[v]}, add it to the queue", 1.1, roles, labels,
                                  "Queue", q, (u, v))
            else:
                yield graph_frame(10, f"{v} was already seen: skip it", 0.7, roles, labels, "Queue", q, (u, v))
        roles[u] = "done"
    out["result"] = str([dist[n] for n in NODES])
    yield graph_frame(16, "Done. Every node has its shortest distance from A.", 3.0, roles, labels, "Queue", q)


# ---------- DFS ----------
DFS_JAVA = """static void dfs(List<List<Integer>> g, int u,
                boolean[] seen, List<Integer> order) {
    seen[u] = true;
    order.add(u);
    for (int v : g.get(u)) {
        if (!seen[v]) {
            dfs(g, v, seen, order);
        }
    }
}"""


def _dfs(out):
    roles = {n: "unseen" for n in NODES}
    labels, order, stack = {}, [], []
    yield graph_frame(None, "Visit every node by going deep first, then backtracking.", 2.0, roles, labels,
                      "Call stack", stack)

    def go(u):
        order.append(u)
        stack.append(u)
        roles[u], labels[u] = "current", f"#{len(order)}"
        yield graph_frame(3, f"Visit {u}: it is number {len(order)} in the visit order", 1.1, roles, labels,
                          "Call stack", stack)
        for v in ADJ[u]:
            if v in order:
                yield graph_frame(6, f"{v} was already visited: skip it", 0.7, roles, labels, "Call stack", stack,
                                  (u, v))
            else:
                yield graph_frame(6, f"{v} is new: go deeper into {v}", 0.9, roles, labels, "Call stack", stack,
                                  (u, v))
                roles[u] = "queued"
                yield from go(v)
                roles[u] = "current"
                yield graph_frame(7, f"Back at {u}: check its next neighbor", 0.7, roles, labels, "Call stack",
                                  stack)
        roles[u] = "done"
        stack.pop()
        yield graph_frame(9, f"{u} has no unvisited neighbors left: backtrack", 0.8, roles, labels, "Call stack",
                          stack)

    yield from go("A")
    out["result"] = str([NODES.index(n) for n in order])
    yield graph_frame(10, "Done. Visit order: " + " ".join(order), 3.0, roles, labels, "Call stack", stack)


# ---------- registry ----------
@dataclass
class Tracer:
    id: str
    title: str
    subtitle: str
    aliases: tuple
    java: str
    complexity: str
    how: list
    why: str
    pitfall: str
    use: str
    gen: Callable
    java_helpers: str
    java_main: str

    def run(self):
        """Return (frames, result_str)."""
        out = {}
        frames = list(self.gen(out))
        return frames, out["result"]

    def facts(self):
        numbered = "\n".join(f"{i:>2} {ln}" for i, ln in enumerate(self.java.split("\n"), 1))
        return {"id": self.id, "title": self.title, "tagline": self.subtitle, "complexity": self.complexity,
                "how_it_works": self.how, "why_it_matters": self.why, "watch_out": self.pitfall,
                "real_life_use": self.use, "java_code_shown_in_video": numbered}


SWAP = "static void swap(int[] a, int i, int j) { int t = a[i]; a[i] = a[j]; a[j] = t; }"
GRAPH_JAVA = """static List<List<Integer>> graph() {
        String[] e = {"0 1", "0 2", "1 3", "1 4", "2 4", "2 5", "4 6", "5 6"};
        List<List<Integer>> g = new ArrayList<>();
        for (int i = 0; i < 7; i++) g.add(new ArrayList<>());
        for (String s : e) { String[] p = s.split(" "); int a = Integer.parseInt(p[0]), b = Integer.parseInt(p[1]);
            g.get(a).add(b); g.get(b).add(a); }
        for (List<Integer> l : g) Collections.sort(l);
        return g;
    }"""

TRACERS = {t.id: t for t in [
    Tracer("mergesort", "Merge Sort", "Split in half. Sort each half. Merge.", ("merge sort", "mergesort"),
           MERGE_JAVA, "Time O(n log n) always · Space O(n)",
           ["Split the array in half until each piece has one element",
            "A single element is already sorted",
            "Merge two sorted halves by repeatedly taking the smaller front element",
            "Keep merging until one sorted array remains"],
           "Guaranteed O(n log n) whatever the input order, and it is stable: equal items keep their order.",
           "It needs O(n) extra memory for the temporary array.",
           "Sorting linked lists, sorting files too big for memory, and any sort where ties must keep their order.",
           _mergesort, "", "int[] a = {38, 27, 43, 3, 9, 82, 10, 55}; mergeSort(a, new int[a.length], 0, a.length - 1);\n"
                            "        System.out.println(Arrays.toString(a));"),
    Tracer("binarysearch", "Binary Search", "Cut the search space in half every step.", ("binary search",),
           BINARY_JAVA, "Time O(log n) · Space O(1) · Needs sorted input",
           ["Look at the middle element",
            "If it equals the target, you are done",
            "If it is smaller than the target, throw away the left half; if larger, the right half",
            "Repeat on what is left until you find it or the range is empty"],
           "Each step halves the problem, so a billion sorted items need only about 30 comparisons.",
           "The array must be sorted. Compute mid as lo + (hi - lo) / 2 so it cannot overflow.",
           "Finding a record in a sorted index, bisecting a list of commits to find the one that broke a build.",
           _binarysearch, "", "int[] a = {3, 8, 12, 17, 21, 25, 31, 38, 42, 57, 63, 79};\n"
                              "        System.out.println(binarySearch(a, 57) + \" \" + binarySearch(a, 40));"),
    Tracer("bfs", "Breadth-First Search", "Explore the graph level by level.", ("breadth-first", "breadth first", "bfs"),
           BFS_JAVA, "Time O(V + E) · Space O(V)",
           ["Put the start node in a queue with distance 0",
            "Take the next node out of the queue",
            "Give every neighbor not seen yet distance + 1 and add it to the queue",
            "Repeat until the queue is empty"],
           "It finds the fewest hops from the start to every reachable node in an unweighted graph.",
           "Mark a node as seen when you add it to the queue, not when you take it out, or you queue duplicates.",
           "Shortest path in a maze or a social network, web crawlers, and finding everything within N steps.",
           _bfs, GRAPH_JAVA, "System.out.println(Arrays.toString(bfs(graph(), 0)));"),
    Tracer("bubblesort", "Bubble Sort", "Swap neighbors until nothing moves.", ("bubble sort", "bubblesort"),
           BUBBLE_JAVA, "Time O(n²) · O(n) if already sorted · Space O(1)",
           ["Compare each pair of neighbors",
            "Swap them if they are in the wrong order",
            "After one full pass the largest value has bubbled to the end",
            "Repeat, and stop early if a pass makes no swaps"],
           "The easiest sort to understand, which makes it a good first example for reasoning about loops.",
           "It does O(n²) comparisons: fine for learning, not for real workloads.",
           "Teaching, and tiny or nearly sorted inputs where the early exit makes it close to O(n).",
           _bubblesort, SWAP, "int[] a = {6, 3, 8, 2, 9, 1, 5}; bubbleSort(a);\n        System.out.println(Arrays.toString(a));"),
    Tracer("dfs", "Depth-First Search", "Go deep first, then backtrack.", ("depth-first", "depth first", "dfs"),
           DFS_JAVA, "Time O(V + E) · Space O(V)",
           ["Mark the current node as visited",
            "Look at each neighbor in turn",
            "If a neighbor is new, go deeper into it before anything else",
            "When a node has no new neighbors left, backtrack"],
           "It follows one path all the way before trying another, which suits path existence, cycle detection and topological sorting.",
           "Very deep graphs can overflow the recursion stack. Use an explicit stack for huge inputs.",
           "Solving mazes, detecting cycles in dependency graphs, and finding connected components.",
           _dfs, GRAPH_JAVA, "List<Integer> order = new ArrayList<>(); dfs(graph(), 0, new boolean[7], order);\n"
                             "        System.out.println(order);"),
    Tracer("insertionsort", "Insertion Sort", "Grow a sorted section one card at a time.", ("insertion sort", "insertionsort"),
           INSERTION_JAVA, "Time O(n²) · O(n) if nearly sorted · Space O(1)",
           ["Treat the left part as already sorted",
            "Take the next element, the key",
            "Shift every larger sorted element one step to the right",
            "Drop the key into the gap"],
           "It is very fast on small or nearly sorted data, which is why it shows up inside real library sorts for small ranges.",
           "It shifts many elements on reverse-ordered input: O(n²).",
           "Sorting small arrays, and keeping a list sorted as new items arrive one at a time.",
           _insertionsort, "", "int[] a = {7, 3, 9, 1, 6, 2, 8, 4}; insertionSort(a);\n        System.out.println(Arrays.toString(a));"),
    Tracer("quicksort", "Quick Sort", "Pick a pivot. Split. Repeat.", ("quick sort", "quicksort"),
           QUICK_JAVA, "Time O(n log n) average, O(n²) worst · Space O(log n)",
           ["Pick a pivot, here the last element",
            "Move everything smaller than the pivot to its left",
            "Put the pivot in its final position",
            "Repeat on the left part and the right part"],
           "Average O(n log n) with small constant factors, and it sorts in place.",
           "A bad pivot on already sorted data degrades to O(n²). Real versions pick pivots randomly or by median of three.",
           "General purpose in-memory sorting.",
           _quicksort, SWAP, "int[] a = {38, 27, 43, 3, 9, 10, 55, 19, 64, 82}; quickSort(a, 0, a.length - 1);\n"
                             "        System.out.println(Arrays.toString(a));"),
]}


def java_program(t):
    """A complete Main.java for t, used by the tests to compile and run the code shown on screen."""
    body = "\n".join("    " + ln if ln else ln for ln in t.java.split("\n"))
    return ("import java.util.*;\npublic class Main {\n    " + t.java_helpers + "\n" + body +
            "\n    public static void main(String[] args) {\n        " + t.java_main + "\n    }\n}\n")


def used_algos(texts):
    """Ids of algorithms already covered by any of the given post texts/topics."""
    low = [t.lower() for t in texts]
    return {t.id for t in TRACERS.values() if any(al in s for al in t.aliases for s in low)}


def next_algo(texts):
    """First registered algorithm that has not been posted or queued yet (None when exhausted)."""
    done = used_algos(texts)
    return next((t for t in TRACERS.values() if t.id not in done), None)


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(TRACERS[sys.argv[1]].facts(), indent=2, ensure_ascii=False))
    else:
        for t in TRACERS.values():
            frames, result = t.run()
            print(f"{t.id:14} frames={len(frames):3} duration={sum(f['dur'] for f in frames):5.1f}s result={result}")
