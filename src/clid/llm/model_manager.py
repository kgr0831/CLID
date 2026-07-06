"""SequentialSwapManager — one model owns the GPU at a time.

The blueprint's core memory strategy: never co-resident Orchestrator + Coder.
The pipeline calls :meth:`use` to obtain the right client for the current phase;
when the required phase differs from what's loaded, a *swap* is recorded (weights
reload from the warm RAM page cache). In ``concurrent`` strategy no swap is emitted.

In ``mock`` backend the swap is only logged (no real load). In ``openai`` backend
this is where a production deployment would call the serving engine to load/unload
GGUF weights; we expose :meth:`estimated_swap_seconds` for that accounting.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from .client import LLMClient, MockLLM, OpenAICompatLLM

ORCHESTRATOR = "orchestrator"
CODER = "coder"


@dataclass
class SwapEvent:
    frm: str | None
    to: str
    weights_gb: float
    est_seconds: float
    note: str


class SequentialSwapManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.strategy = settings.strategy_mode
        self.current: str | None = None
        self.swaps: list[SwapEvent] = []
        self._clients: dict[str, LLMClient] = {}

    # ---- client construction ---------------------------------------------
    def _client(self, phase: str) -> LLMClient:
        if phase in self._clients:
            return self._clients[phase]
        if self.settings.backend == "mock":
            client: LLMClient = MockLLM(role=phase)
        else:
            ep = getattr(self.settings, phase)
            client = OpenAICompatLLM(ep.base_url, ep.model, ep.api_key, role=phase)
        self._clients[phase] = client
        return client

    # ---- resource accounting ---------------------------------------------
    def _weights_gb(self, phase: str) -> float:
        toml = self.settings.models_toml
        if phase == ORCHESTRATOR:
            return float(toml.get("orchestrator", {}).get("weights_gb", 18))
        coder = toml.get("coder", {})
        scen = coder.get("scenario", "A")
        return float(coder.get(f"scenario_{scen}", {}).get("weights_gb", 19))

    def estimated_swap_seconds(self, weights_gb: float) -> float:
        # Warm RAM page cache → PCIe/VRAM copy, ~24 GB/s effective. Conservative.
        return round(weights_gb / 20.0, 2)

    # ---- the one call the pipeline makes ---------------------------------
    def use(self, phase: str) -> tuple[LLMClient, SwapEvent | None]:
        client = self._client(phase)
        swap: SwapEvent | None = None
        needs_swap = (
            self.strategy == "sequential_swap"
            and self.current is not None
            and self.current != phase
        )
        if needs_swap or (self.current is None and self.strategy == "sequential_swap"):
            w = self._weights_gb(phase)
            secs = self.estimated_swap_seconds(w)
            verb = "load" if self.current is None else f"swap {self.current}→{phase}"
            swap = SwapEvent(self.current, phase, w, secs,
                             f"{verb}: {phase} weights ~{w:.0f}GB, ~{secs:.1f}s (warm cache)")
            self.swaps.append(swap)
        self.current = phase
        return client, swap

    def orchestrator(self) -> tuple[LLMClient, SwapEvent | None]:
        return self.use(ORCHESTRATOR)

    def coder(self) -> tuple[LLMClient, SwapEvent | None]:
        return self.use(CODER)
