"""End-to-end pipeline runs on the mock backend (offline)."""

import tempfile
import unittest
from pathlib import Path

from clid.config import get_settings
from clid.graph.pipeline import Pipeline


def _pipeline(tmp: str, run_id: str) -> Pipeline:
    settings = get_settings()
    settings.workspaces_dir = Path(tmp) / "workspaces"
    settings.runs_dir = Path(tmp) / "runs"
    assert settings.backend == "mock"
    return Pipeline(settings, run_id)


class TestPipeline(unittest.TestCase):
    def test_clean_run_passes_first_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe = _pipeline(tmp, "clean")
            final = pipe.run("Build a Python calculator library with tests")
            self.assertEqual(final["status"], "done")
            self.assertEqual(final["iterations"], 0)
            result = final["result"]
            self.assertTrue(result["tests_passed"])
            self.assertIn("calculator/operations.py", result["files"])
            self.assertIn("tests/test_operations.py", result["files"])

    def test_demo_bug_recovers_via_L1_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe = _pipeline(tmp, "bugged")
            final = pipe.run("calculator library", demo_bug=True)
            self.assertEqual(final["status"], "done")
            self.assertEqual(final["iterations"], 1)  # exactly one rewrite loop
            self.assertTrue(final["result"]["tests_passed"])
            ops = pipe.ws.read("calculator/operations.py")
            self.assertIn('raise ValueError("division by zero")', ops)  # fix applied

    def test_sequential_swaps_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe = _pipeline(tmp, "swaps")
            final = pipe.run("calculator library")
            # load orch, swap→coder, swap→orch = 3 swaps minimum on a clean run
            self.assertGreaterEqual(final["result"]["swaps"], 3)
            self.assertEqual(pipe.manager.swaps[0].to, "orchestrator")

    def test_generic_fallback_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipe = _pipeline(tmp, "generic")
            final = pipe.run("make a widget parser thing")
            self.assertEqual(final["status"], "done")
            self.assertTrue(final["result"]["tests_passed"])


if __name__ == "__main__":
    unittest.main()
