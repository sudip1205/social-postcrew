"""The Explainroo Producer: the renderer is registered, the checks are read, the words the voice says cannot be changed."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from helpers import TempWorkspace  # noqa: E402

from postcrew import platforms  # noqa: E402
from postcrew.agents.base import AgentError  # noqa: E402
from postcrew.agents.explainroo import ExplainrooAgent, narration_of  # noqa: E402
from postcrew.agents.supervisor import crew_for  # noqa: E402


class ExplainrooToolTests(unittest.TestCase):
    def test_the_renderer_replaces_the_video_producer(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"]["video"]["renderer"] = "explainroo"
            ws.save_config(cfg)
            view = platforms.view(ws.config(), "youtube")
            media = [a for a in crew_for("youtube", view, "short-tip") if a.id == "media"][0]
            self.assertIsInstance(media, ExplainrooAgent)

    def test_a_topic_can_choose_it_too(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"]["categories"]["short-tip"]["renderer"] = "explainroo"
            ws.save_config(cfg)
            view = platforms.view(ws.config(), "youtube")
            self.assertEqual(platforms.renderer_for(view, "short-tip"), "explainroo")

    def test_markers_and_notes_are_not_words_but_the_words_are(self):
        md = "# Title\n\n## scene1 {hold=1}\nLeft starts [#start] at {SQL|sequel} zero.\n> a note\n[pause 0.5]\n"
        self.assertEqual(narration_of(md), ["left", "starts", "at", "sql", "zero"])

    def test_it_asks_for_the_install_folder(self):
        class Ctx:
            cfg = {"video": {}}
        with self.assertRaises(AgentError) as e:
            ExplainrooAgent().tool(Ctx())
        self.assertIn("not installed", str(e.exception))

    def test_check_issues_become_problems_and_voice_noise_is_ignored(self):
        data = {"issues": [{"level": "error", "scene": "scene2", "t": 5.75, "message": "\"a\" overlaps \"b\""},
                           {"level": "warn", "scene": "scene1", "t": None, "message": "the voice check could not confirm \"one-pass\"."},
                           {"level": "warn", "scene": "scene3", "t": 2, "message": "text is small"}]}
        agent = ExplainrooAgent()
        with mock.patch.object(agent, "node", return_value=(1, json.dumps(data))):
            found = agent.problems(Path("."), "videos/x")
        self.assertEqual(len(found), 2)
        self.assertTrue(found[0].startswith("error: scene2 at 5.75s"))

    def test_settings_validate(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"]["enabled"] = True   # a switched-off app is not checked
            cfg["platforms"]["youtube"]["video"]["renderer"] = "nonsense"
            with self.assertRaises(ValueError):
                ws.save_config(cfg)


if __name__ == "__main__":
    unittest.main()


class PauseAuditTests(unittest.TestCase):
    def words(self, spec):
        out, t = [], 0.0
        for text, gap in spec:
            out.append({"text": text, "start": t, "end": t + 0.3})
            t += 0.3 + gap
        return out

    def test_a_voice_that_stops_where_the_punctuation_says_is_clean(self):
        from postcrew.agents.explainroo import pause_problems
        self.assertEqual(pause_problems(self.words([("In", 0.05), ("Python,", 0.3), ("a", 0.05), ("list", 0.05), ("works.", 0.6), ("Done.", 0)])), [])

    def test_wrong_stops_are_found(self):
        from postcrew.agents.explainroo import pause_problems
        found = pause_problems(self.words([("Brackets", 0.05), ("close", 0.6), ("last", 0.05), ("opened,", 0.0), ("then", 0.05),
                                           ("go", 0.05), ("here,", 0.02), ("now", 0.02), ("done.", 0.1), ("Next.", 0)]))
        kinds = " ".join(w + ":" + k for w, k in found)
        self.assertIn("close:it stops in the middle of a phrase", kinds)
        self.assertIn("here,:the comma was run on", kinds)
        self.assertIn("done.:no stop after the sentence end", kinds)
