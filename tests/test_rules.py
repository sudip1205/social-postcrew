"""The owner's rules live in ONE file, postcrew/rules/script-rules.md (owner, 2026-11-26: "No rule in the agent code")."""
import ast
import unittest
from pathlib import Path

from postcrew import rules

ROOT = Path(__file__).resolve().parents[1] / "postcrew"


class RulesFileTests(unittest.TestCase):
    def test_the_file_has_the_plan_script_and_tag_parts(self):
        self.assertEqual(set(rules.parts()), {"plan", "script", "tags"})
        for key in ("CATCH LINE", "Technical depth", "No code unless asked", "never put a colon", "The camera", "nameOn"):
            self.assertIn(key, rules.script())
        self.assertIn("Technical depth", rules.plan())
        self.assertIn("15-25 tags", rules.plan())

    def test_no_rule_constants_are_left_in_the_agent_code(self):
        gone = {"HOOK_RULE", "NO_CODE_RULE", "DEPTH_RULE", "LABEL_RULE", "CAMERA_RULE", "SPEECH_RULE", "TAG_RULE", "DEPTH_PLAN_RULE"}
        for f in ROOT.rglob("*.py"):
            names = {t.id for n in ast.walk(ast.parse(f.read_text())) if isinstance(n, ast.Assign)
                     for t in n.targets if isinstance(t, ast.Name)}
            self.assertFalse(names & gone, f"{f.name} defines {names & gone}")


if __name__ == "__main__":
    unittest.main()
