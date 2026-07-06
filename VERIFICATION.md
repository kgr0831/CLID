# CLID — Verification Report (no hardware)

**Constraint:** the target RTX 4090 (24GB) + 64GB machine is not available.
**Approach:** validate the *design and implementation* with everything that does
**not** require the physical GPU, and explicitly separate what still does.

Reproduce all of this with:

```bash
PYTHONPATH=src python -m clid.cli --verify                 # resource model + functional self-checks
PYTHONPATH=src python -m unittest discover -s tests -t .   # 29 tests
```

Status: **29/29 tests pass · 14/14 `--verify` checks pass.**

---

## 1. Resource model — computed, not measured

`src/clid/resource.py` encodes each model's published attention config and derives
KV-cache/VRAM from first principles:

```
GQA/MHA : 2·layers·kv_heads·head_dim·dtype_bytes   (per token)
MLA     : layers·(kv_lora_rank + rope_dim)·dtype_bytes
```

For models with a **public** architecture this reproduces the blueprint's
theoretical slot counts — a hardware-free consistency check on the numbers.

| Model | attn | weights | KV/token | GB/slot @8K | slots (computed) | blueprint | verified |
|-------|------|--------:|---------:|------------:|-----------------:|----------:|:--------:|
| Qwen3-Coder-30B-A3B | GQA | 19.0 | 96.0 KB | 0.75 | **4** | 4 | no* |
| DeepSeek-Coder-V2-Lite-16B | MLA | 9.0 | 30.4 KB | 0.237 | **56** | 57 | yes |
| Qwen2.5-Coder-14B | GQA | 9.5 | 192 KB | 1.50 | **8** | 9 | yes |
| Qwen2.5-Coder-7B | GQA | 4.5 | 56.0 KB | 0.438 | **41** | 41 | yes |

`*` newer/2026 MoE — representative params pending model-card confirmation; same methodology.

**Findings**
- Every intended model fits **single-resident** in 24GB at 8K (no offloading needed) — the
  sequential-swap premise holds. ✅
- MLA (DeepSeek) yields **~7× more concurrent slots** than same-weight GQA — confirms the
  Scenario-B "high-parallel + merge" rationale. ✅
- Orchestrator (Qwen3.6-35B-A3B, 18GB Q4): KV budget ~4.5GB → **~24.5K tokens** of fp16 KV.
  The **262K native context cannot be fully materialized in fp16** on 24GB; it needs KV
  quantization (Q8 ≈ 2×, Q4 ≈ 4×). Consistent with the design keeping non-`design` modes ≤8K. ⚠️ (honest gap, not a failure)
- Both weights (18+19≈37GB) sit warm in 64GB RAM with ~19GB to spare → fast swap. ✅

## 2. Backend parity — real HTTP path, no GPU

`tests/test_openai_backend.py` stands up a stdlib server speaking the OpenAI
`/chat/completions` protocol and runs the **entire pipeline** against it over a real
socket with `CLID_BACKEND=openai`. Proves transport, JSON round-trip, response
parsing, and sequential-swap wiring — i.e. it will run against real llama.cpp / TabbyAPI
servers by only changing the endpoint. ✅

## 3. Functional correctness — offline mock

The mock backend emits a **real, compilable** project so the review loop genuinely
builds and tests it.

- Clean run: 6 stages → PASS on first review, 0 iterations, 3 swaps, tests execute. ✅
- L1 self-repair: injected bug → judge routes `coder→rewrite` → fixed in exactly one loop. ✅
- Escalation ladder unit-verified at every boundary: L1 rewrite → L2 redelegate →
  L3 redesign → L4 halt. A never-converging bug climbs to **halt** (no infinite loop). ✅
- Sequential strategy records swaps; **concurrent** strategy records none. ✅

### Test matrix (29)

| Suite | n | Covers |
|-------|--:|--------|
| test_engine | 5 | StateGraph flow, conditional loops, reducers, checkpointing, guards |
| test_tools | 5 | workspace path-safety, manifest (top-level only), templater, compile/test runners |
| test_pipeline | 4 | end-to-end clean, L1 recovery, swaps recorded, generic fallback |
| test_resource | 7 | fit in 24GB, KV formulas, blueprint reproduction, orch context limit |
| test_escalation | 7 | judge routing L1–L4, persistent-failure→halt, seq vs concurrent swaps |
| test_openai_backend | 1 | full pipeline over real HTTP OpenAI-compatible endpoint |

---

## 4. Still requires the physical RTX 4090

These are **empirical** properties that no amount of offline validation can establish —
they are honestly out of scope until the hardware is available:

- Actual decode throughput (tok/s) per model and quant.
- True concurrent slot count under **GPU-compute** (not just memory) bottleneck — the
  computed slot counts above are the *memory* ceiling; real usable slots are lower.
- Real quantized-model output quality / SWE-bench pass rate.
- Measured warm-cache swap latency on the specific NVMe + PCIe.
- KV-quantization quality trade-off at extended (>24K) context.

**Recommended first step on real hardware:** serve Qwen3.6-35B-A3B and Qwen3-Coder-30B
via llama.cpp, point `.env` at them (`CLID_BACKEND=openai`), and run `--verify` plus a
real build request. Because §2 already proved the HTTP path, only the empirical numbers
above remain to be measured.
