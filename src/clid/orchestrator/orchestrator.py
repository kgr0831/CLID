"""Orchestrator: the single judgement model cycled through five modes.

Every mode runs in Phase A. The Orchestrator asks the SequentialSwapManager for
the Phase-A client (recording a swap if the Coder had the GPU), builds the mode's
user prompt, calls the backend, and validates the result against ``schemas``.
"""

from __future__ import annotations

import json

from ..config import Settings
from ..llm import SequentialSwapManager, SwapEvent
from ..schemas import (
    Classification,
    Delegation,
    Design,
    Diagnosis,
    JudgeVerdict,
)


class Orchestrator:
    def __init__(self, manager: SequentialSwapManager, settings: Settings) -> None:
        self.manager = manager
        self.settings = settings

    def _run(self, mode: str, user: str, context: dict, schema):
        client, swap = self.manager.orchestrator()
        raw = client.chat(
            mode=mode,
            system=self.settings.prompt(mode),
            user=user,
            context=context,
        )
        return schema.model_validate(raw), swap

    # ── 1 · classify ──────────────────────────────────────────────────────
    def classify(self, request: str) -> tuple[Classification, SwapEvent | None]:
        user = f"Classify this request:\n\n{request}"
        return self._run("classify", user, {"request": request}, Classification)

    # ── 2 · design ────────────────────────────────────────────────────────
    def design(self, request: str, classification: Classification) -> tuple[Design, SwapEvent | None]:
        user = (
            f"Request: {request}\n"
            f"Domain: {classification.domain} · type: {classification.project_type}\n\n"
            "Design the directory structure and per-file coding plan."
        )
        return self._run("design", user, {"request": request}, Design)

    # ── 3 · delegate ──────────────────────────────────────────────────────
    def delegate(self, request: str, design: Design) -> tuple[Delegation, SwapEvent | None]:
        user = (
            "Decompose this design into per-file Coder tasks.\n\n"
            + json.dumps(design.model_dump(), indent=2, ensure_ascii=False)
        )
        return self._run("delegate", user, {"request": request}, Delegation)

    # ── 5 · diagnose ──────────────────────────────────────────────────────
    def diagnose(self, request: str, tool_report: str) -> tuple[Diagnosis, SwapEvent | None]:
        user = (
            "Deterministic tools produced this report. Diagnose cross-file issues:\n\n"
            + tool_report
        )
        return self._run("diagnose", user, {"request": request, "tool_output": tool_report}, Diagnosis)

    # ── 6 · judge ─────────────────────────────────────────────────────────
    def judge(self, request: str, *, tool_output: str, focus_path: str,
              retries: dict, thresholds: dict) -> tuple[JudgeVerdict, SwapEvent | None]:
        user = (
            "The test/build tools failed. Decide the fix route.\n\n"
            f"Focus file: {focus_path}\nRetries so far: {retries}\n\n"
            f"Tool output:\n{tool_output}"
        )
        ctx = {
            "request": request,
            "tool_output": tool_output,
            "focus_path": focus_path,
            "retries": retries,
            "thresholds": thresholds,
        }
        return self._run("judge", user, ctx, JudgeVerdict)
