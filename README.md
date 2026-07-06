# CLID — Local Coding-Agent Orchestration

A heterogeneous multi-agent coding framework for a **single RTX 4090 (24GB) + 64GB RAM**.
Built from the [architecture blueprint](docs/): six logical roles, **two resident models**,
**sequential-swap** memory strategy, **no offloading**.

```
사용자 요청
   │
   ▼
1 Master ─classify─┐
2 Sub    ─design───┤  Orchestrator (one model, 5 modes)
3 Runner ─delegate─┘        │
   │                        ▼
4 Coder  ───────────► generation model (Coder)
   │
5 Synthesizer ─diagnose─┐  deterministic tools + Orchestrator
6 Hybrid Review ─judge──┘  compiler · linter · test runner
   │
   ├─ pass ──────────► 최종 출력
   └─ fail ──► L1 rewrite→Coder · L2 redelegate→Runner · L3 redesign→Sub · L4 halt
```

## Design decisions

| Decision | Rationale |
|----------|-----------|
| 6 roles → **2 models** (Orchestrator w/ 5 modes + Coder) | 5 judgement roles share one model; only generation is separate. Avoids swap/stream latency. |
| **Sequential swap**, no offloading | Pipeline is inherently sequential; one model owns 24GB at a time. Both fit Q4 in 24GB. |
| Review = **tools decide pass/fail, Orchestrator only diagnoses failures** | 4-bit resident capable model beats both slow-offload and tiny-SLM reviewers. |
| Domain-specialized Coders = **system-prompt injection, not extra weights** | Keeps VRAM for batch slots. |

## Backends

CLID has one `LLMClient` interface with two backends:

- **`mock`** (default) — deterministic, offline. Runs the entire pipeline with no GPU/servers.
  The mock generator emits a real, compilable project so the review loop genuinely builds & tests it.
- **`openai`** — OpenAI-compatible HTTP (llama.cpp server or ExLlamaV3+TabbyAPI). Point it at
  your local Orchestrator/Coder endpoints.

## Quick start

```bash
# from the repo root
python -m clid.cli "Build a Python calculator library with add/sub/mul/div and tests"

# inspect a run
python -m clid.cli --list-runs
python -m clid.cli --show-run <run_id>

# use real local models instead of the mock
cp .env.example .env      # set CLID_BACKEND=openai and the endpoints
```

Requires Python ≥ 3.11 (`tomllib`), `pydantic`, `httpx`. Everything else is optional
(`openai` for the HTTP backend, `tree-sitter` for the richer manifest, `pytest` for dev).

## Layout

```
config/            models.toml + per-mode system prompts
src/clid/
  graph/           LangGraph-compatible StateGraph engine + PipelineState
  llm/             LLMClient (mock / openai) + SequentialSwapManager
  orchestrator/    the 5 modes
  coder/           generation node
  tools/           workspace · runners · manifest · sandbox
  cli.py           entrypoint
tests/
```

The `graph` engine mirrors LangGraph's API (`add_node`, `add_conditional_edges`,
`compile`, checkpointer) so it can be swapped for real LangGraph without touching the
pipeline definition.
