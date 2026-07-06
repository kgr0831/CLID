"""Escalation ladder (L1→L2→L3→L4) and sequential/concurrent swap behavior."""

import tempfile
import unittest
from pathlib import Path

from clid.config import Settings, get_settings
from clid.graph.pipeline import Pipeline
from clid.llm import CODER, ORCHESTRATOR, MockLLM, SequentialSwapManager


class TestJudgeRoutingPolicy(unittest.TestCase):
    """The escalation decision is made by the judge; verify each boundary."""

    def setUp(self):
        self.judge = MockLLM("orchestrator")
        self.thr = {"rewrite_retries": 2, "redelegate_retries": 2, "redesign_retries": 1}

    def _route(self, retries):
        v = self.judge.chat(mode="judge", system="", user="",
                            context={"retries": retries, "thresholds": self.thr,
                                     "focus_path": "x.py", "tool_output": "boom"})
        return v["route"]

    def test_l1_rewrite_first(self):
        self.assertEqual(self._route({"rewrite": 0, "redelegate": 0, "redesign": 0}), "coder")

    def test_l2_redelegate_after_rewrites_exhausted(self):
        self.assertEqual(self._route({"rewrite": 2, "redelegate": 0, "redesign": 0}), "runner")

    def test_l3_redesign_after_redelegate_exhausted(self):
        self.assertEqual(self._route({"rewrite": 2, "redelegate": 2, "redesign": 0}), "sub")

    def test_l4_halt_after_everything_exhausted(self):
        self.assertEqual(self._route({"rewrite": 2, "redelegate": 2, "redesign": 1}), "halt")


class TestPersistentFailureEscalates(unittest.TestCase):
    def test_never_converging_bug_climbs_to_halt(self):
        settings = get_settings()
        with tempfile.TemporaryDirectory() as tmp:
            settings.workspaces_dir = Path(tmp) / "ws"
            settings.runs_dir = Path(tmp) / "runs"
            pipe = Pipeline(settings, "persist")
            pipe.thresholds = {"rewrite_retries": 1, "redelegate_retries": 1,
                               "redesign_retries": 1, "global_budget_iters": 6}
            final = pipe.run("calculator library", persist_fail=True)
        self.assertEqual(final["status"], "halted")
        self.assertGreater(final["iterations"], 6)
        joined = "\n".join(final["log"])
        # every escalation tier was exercised on the way to halt
        self.assertIn("redelegate", joined)
        self.assertIn("redesign", joined)
        self.assertIn("HALT", joined)


class TestSwapStrategies(unittest.TestCase):
    def _settings(self, mode: str) -> Settings:
        base = get_settings()
        return Settings(
            backend="mock", sandbox="local",
            orchestrator=base.orchestrator, coder=base.coder,
            strategy_mode=mode, models_toml=base.models_toml,
        )

    def test_sequential_swap_records_swaps(self):
        mgr = SequentialSwapManager(self._settings("sequential_swap"))
        _, s1 = mgr.use(ORCHESTRATOR)   # initial load
        _, s2 = mgr.use(CODER)          # swap
        _, s3 = mgr.use(ORCHESTRATOR)   # swap back
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertIsNotNone(s3)
        self.assertEqual(len(mgr.swaps), 3)

    def test_concurrent_mode_never_swaps(self):
        mgr = SequentialSwapManager(self._settings("concurrent"))
        for phase in (ORCHESTRATOR, CODER, ORCHESTRATOR, CODER):
            _, swap = mgr.use(phase)
            self.assertIsNone(swap)
        self.assertEqual(len(mgr.swaps), 0)


if __name__ == "__main__":
    unittest.main()
