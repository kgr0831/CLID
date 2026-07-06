"""Coder: the generation model. Runs in Phase B (swaps in over the Orchestrator).

Domain specialization (test-harness engineer, endpoint implementer, …) is achieved
by the Runner's per-file ``system_prompt`` — NOT by loading a second model. This
keeps VRAM free for parallel Coder slots.
"""

from __future__ import annotations

from ..config import Settings
from ..llm import SequentialSwapManager, SwapEvent
from ..schemas import CoderOutput, DelegateTask


class Coder:
    def __init__(self, manager: SequentialSwapManager, settings: Settings) -> None:
        self.manager = manager
        self.settings = settings

    def generate(
        self,
        request: str,
        task: DelegateTask,
        *,
        attempt: int = 0,
        demo_bug: bool = False,
        correction: str = "",
    ) -> tuple[CoderOutput, SwapEvent | None]:
        client, swap = self.manager.coder()
        # The Runner's per-file system prompt specializes this Coder instance.
        system = task.system_prompt + "\n\n" + self.settings.prompt("coder")
        user_parts = [
            f"Build the file: {task.path}",
            f"Instructions:\n{task.instructions}",
        ]
        if task.context_files:
            user_parts.append("Context files (signatures only): " + ", ".join(task.context_files))
        if task.acceptance:
            user_parts.append(f"Acceptance: {task.acceptance}")
        if correction:
            user_parts.append(f"CORRECTION (apply fully): {correction}")
        user = "\n\n".join(user_parts)

        context = {
            "request": request,
            "path": task.path,
            "attempt": attempt,
            "demo_bug": demo_bug,
            "correction": correction,
        }
        raw = client.chat(mode="coder", system=system, user=user, context=context)
        out = CoderOutput.model_validate(raw)
        if not out.path:
            out.path = task.path
        return out, swap
