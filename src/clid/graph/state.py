"""PipelineState — the channels that flow through the DAG.

Kept as a plain ``dict`` (JSON-serializable) so the checkpointer can snapshot
it. This module documents the schema and provides a constructor + the reducer
map the engine needs (``log`` and ``events`` are append channels).
"""

from __future__ import annotations

from typing import Any, TypedDict

from .engine import append_reducer


class PipelineState(TypedDict, total=False):
    # ── input ──────────────────────────────────────────────────────────────
    request: str                     # user's natural-language request
    workspace: str                   # absolute path where files are written
    thread_id: str

    # ── stage outputs ──────────────────────────────────────────────────────
    classification: dict             # Master  · classify
    design: dict                     # Sub     · design
    delegation: dict                 # Runner  · delegate
    files: dict[str, str]            # path -> content (Coder output)
    diagnosis: dict                  # Synthesizer · diagnose
    review: dict                     # Hybrid Review · judge + tool verdict

    # ── control / loop state ───────────────────────────────────────────────
    phase: str                       # "A" (orchestrator) | "B" (coder)
    retries: dict[str, int]          # {"rewrite": n, "redelegate": n, "redesign": n}
    iterations: int                  # global loop counter (L4 budget)
    focus_path: str                  # file targeted by an active rewrite loop
    status: str                      # running | done | halted
    result: dict                     # final summary

    # ── observability (append channels) ────────────────────────────────────
    log: list[str]
    events: list[dict[str, Any]]


REDUCERS = {"log": append_reducer, "events": append_reducer}


def new_state(request: str, workspace: str, thread_id: str) -> dict:
    return {
        "request": request,
        "workspace": workspace,
        "thread_id": thread_id,
        "files": {},
        "phase": "A",
        "retries": {"rewrite": 0, "redelegate": 0, "redesign": 0},
        "iterations": 0,
        "status": "running",
        "log": [],
        "events": [],
    }
