import unittest

from postcrew import assets
from postcrew.agents import planner
from postcrew.agents.script import finish
from postcrew.render.scenes import FORMATS, draw_frame, parse_edge

LB = {"layout": "diagram", "on_screen": "Load balancer", "narration": "The balancer spreads requests.", "items": [],
      "code": "", "language": "", "seconds": 3,
      "nodes": ["Client", "Load Balancer", "Server A", "Server B"],
      "edges": ["Client > Load Balancer: request", "Load Balancer > Server A: 50%", "Load Balancer > Server B: 50%",
                "Server B > Client: response"]}


class DiagramTests(unittest.TestCase):
    def test_renders_every_format_and_reveal(self):
        for fmt, size in FORMATS.items():
            for reveal in (0.0, 0.5, 1.0):
                self.assertEqual(draw_frame(LB, fmt, "caption", reveal=reveal).size, size)

    def test_parse_edge(self):
        self.assertEqual(parse_edge("client > Load Balancer: request", LB["nodes"]), (0, 1, "request"))
        self.assertIsNone(parse_edge("Client > Nowhere", LB["nodes"]))

    def test_flow_syntax_in_own_script(self):
        s = assets.parse_script("Intro line here.\n\nHow it flows.\nflow: Client > Gateway > Service\n\nEnd.")
        sc = s["scenes"][1]
        self.assertEqual((sc["layout"], sc["nodes"]), ("diagram", ["Client", "Gateway", "Service"]))
        self.assertEqual(sc["edges"], ["Client > Gateway", "Gateway > Service"])

    def test_finish_cleans_nodes(self):
        out = finish({"scenes": [dict(LB, nodes=[" A ", "", "B"], edges=["A > B", " "])]})
        self.assertEqual((out["scenes"][0]["nodes"], out["scenes"][0]["edges"]), (["A", "B"], ["A > B"]))

    def test_idea_context_is_not_matched(self):
        idea = "Circuit breaker :: closed, open, half-open; Resilience4j"
        self.assertEqual(planner.idea_title(idea), "Circuit breaker")
        self.assertTrue(planner.idea_matches(idea, "The circuit breaker pattern"))
        self.assertFalse(planner.idea_matches(idea, "Resilience4j half-open states in Spring"))


if __name__ == "__main__":
    unittest.main()
