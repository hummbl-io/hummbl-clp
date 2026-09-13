"""Captive workflow regression checks; run with python test_ci_workflow.py."""

import unittest
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent / ".github" / "workflows"


class WorkflowRegressionTests(unittest.TestCase):
    def test_repaired_workflow_contract(self):
        for filename in ["ci.yml"]:
            with self.subTest(workflow=filename):
                source = (WORKFLOW_DIR / filename).read_text(encoding="utf-8")
                self.assertIn("uses: actions/setup-python@", source)
                self.assertIn("shell: python", source)
                self.assertIn("check=True", source)
                self.assertNotIn("python.cmd", source)
                self.assertNotIn("$env:USERPROFILE", source)


if __name__ == "__main__":
    unittest.main()
