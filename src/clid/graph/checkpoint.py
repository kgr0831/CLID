"""Checkpointers — snapshot pipeline state after each node.

``MemoryCheckpointer`` keeps snapshots in-process; ``JSONCheckpointer`` also
writes them under ``runs/<thread_id>/`` so a run can be inspected or resumed
after a crash. This is the concrete backing for the blueprint's "LangGraph
state checkpointing" requirement.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def _json_safe(obj: Any) -> Any:
    """Best-effort conversion of a state dict to JSON-serializable form."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # pydantic model?
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return _json_safe(dump())
    return repr(obj)


class MemoryCheckpointer:
    def __init__(self) -> None:
        self.snapshots: dict[str, list[dict]] = {}

    def put(self, thread_id: str, step: int, node: str, state: dict) -> None:
        self.snapshots.setdefault(thread_id, []).append(
            {"step": step, "node": node, "state": copy.deepcopy(state)}
        )

    def latest(self, thread_id: str) -> dict | None:
        snaps = self.snapshots.get(thread_id)
        return snaps[-1]["state"] if snaps else None

    def history(self, thread_id: str) -> list[dict]:
        return self.snapshots.get(thread_id, [])


class JSONCheckpointer(MemoryCheckpointer):
    def __init__(self, root: str | Path) -> None:
        super().__init__()
        self.root = Path(root)

    def put(self, thread_id: str, step: int, node: str, state: dict) -> None:
        super().put(thread_id, step, node, state)
        run_dir = self.root / thread_id
        run_dir.mkdir(parents=True, exist_ok=True)
        safe = _json_safe(state)
        (run_dir / f"{step:03d}_{node}.json").write_text(
            json.dumps({"step": step, "node": node, "state": safe}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # rolling "latest" pointer for quick inspection
        (run_dir / "latest.json").write_text(
            json.dumps(safe, indent=2, ensure_ascii=False), encoding="utf-8"
        )
