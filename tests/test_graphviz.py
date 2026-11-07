"""The graph scene: real nodes and edges, checked so the picture is always true, laid out by the app, and a graph problem now runs."""
import unittest

from postcrew import graphviz, shapes


def step(**kw):
    base = {"say": "start at A", "current": [], "visited": [], "frontier": [], "found": [], "out": [], "edges": [], "labels": [], "note": ""}
    return dict(base, **kw)


BFS = {"title": "BFS from A", "nodes": ["A", "B", "C", "D", "E"], "edges": ["A-B", "A-C", "B-D", "C-D", "D-E"], "directed": False,
       "steps": [step(say="start at A", current=["A"], frontier=["B", "C"], note="queue: B, C"),
                 step(say="then B", current=["B"], visited=["A"], frontier=["C", "D"], edges=["A-B"], labels=["B=1"]),
                 step(say="D is reached", found=["D"], visited=["A", "B", "C"], edges=["B-A", "B-D"], labels=["D=2"])]}


class GraphVizTest(unittest.TestCase):
    def test_a_true_graph_has_no_problems(self):
        self.assertEqual(graphviz.problems(BFS, 1), [])

    def test_an_edge_or_step_naming_a_missing_node_is_refused(self):
        bad = dict(BFS, edges=BFS["edges"] + ["A-Z"])
        self.assertTrue(any("Z" in p for p in graphviz.problems(bad, 2)))
        bad = dict(BFS, steps=[step(current=["Q"])])
        self.assertTrue(any("'Q'" in p for p in graphviz.problems(bad, 2)))
        bad = dict(BFS, steps=[step(edges=["A-E"])])   # not an edge of the graph
        self.assertTrue(any("A-E" in p for p in graphviz.problems(bad, 2)))

    def test_mixed_weights_duplicates_and_self_loops_are_refused(self):
        self.assertTrue(graphviz.problems(dict(BFS, edges=["A-B:3", "A-C"]), 1))
        self.assertTrue(graphviz.problems(dict(BFS, edges=["A-B", "B-A"]), 1))
        self.assertTrue(graphviz.problems(dict(BFS, edges=["A-A"]), 1))
        self.assertEqual(graphviz.problems(dict(BFS, directed=True, edges=["A-B", "B-A"], steps=[step()]), 1), [])   # two ways on a directed graph

    def test_a_directed_edge_is_lit_only_its_own_way(self):
        g = dict(BFS, directed=True, steps=[step(edges=["B-A"])])
        self.assertTrue(any("B-A" in p for p in graphviz.problems(g, 1)))

    def test_layout_puts_nodes_in_layers_from_the_start(self):
        pos = graphviz.layout(BFS)
        self.assertLess(pos["A"][1], pos["B"][1])
        self.assertEqual(pos["B"][1], pos["C"][1])
        self.assertLess(pos["C"][1], pos["D"][1])
        self.assertLess(pos["D"][1], pos["E"][1])
        self.assertTrue(all(0 < x < 1 and 0 <= y <= 1 for x, y in pos.values()))
        self.assertEqual(len({p for p in pos.values()}), 5)   # no two nodes on one spot

    def test_props_carry_weights_lit_edges_and_labels_on_cue(self):
        g = dict(BFS, edges=["A-B:4", "A-C:1", "B-D:1", "C-D:5", "D-E:2"])
        times = iter([0.5, 0.5, 3.0])   # the second step is said at the same moment: it moves just after the first
        out = graphviz.props(g, lambda say, after: next(times))
        self.assertEqual(out["edges"][0], {"a": "A", "b": "B", "w": 4})
        s = out["steps"]
        self.assertEqual([x["t"] for x in s], [0.5, 1.4, 3.0])
        self.assertEqual(s[1]["edges"], [0])
        self.assertEqual(s[2]["edges"], [0, 2])   # "B-A" is the same undirected edge as "A-B"
        self.assertEqual(s[2]["labels"], {"D": "2"})

    def test_a_graph_problem_is_now_drawn_not_stopped(self):
        self.assertEqual(shapes.stop_reason("graph", "reader"), "")
        self.assertEqual(shapes.SCENES["graph"], ("graph",))
        self.assertIn("cannot draw a tree yet", shapes.stop_reason("tree", "reader"))


if __name__ == "__main__":
    unittest.main()
