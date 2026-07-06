"""Resource-model validator — verify the blueprint's VRAM/KV numbers WITHOUT a GPU.

Since the RTX 4090 isn't available, we validate the *design* instead: encode each
model's published attention config and compute, from first principles, the
KV-cache-per-token, per-8K-slot VRAM, how many slots fit in 24 GB, whether each
model fits single-resident, the Orchestrator's max fp16 context, and the RAM
page-cache footprint. Where a model's architecture is public (`verified=True`)
this reproduces the blueprint's theoretical slot counts — a hardware-free check
that the numbers are internally consistent and physically plausible.

KV-cache per token (bytes):
  GQA/MHA :  2 (K,V) · layers · kv_heads · head_dim · dtype_bytes
  MLA     :  layers · (kv_lora_rank + rope_dim) · dtype_bytes      (compressed latent)
"""

from __future__ import annotations

from dataclasses import dataclass, field

GiB = 1024 ** 3
VRAM_GIB = 24.0
RAM_GIB = 64.0
OVERHEAD_GIB = 1.5          # driver + runtime, per models.toml [strategy]
KV_DTYPE_BYTES = 2          # fp16 KV cache (the common default)
OS_GIB = 8.0


@dataclass
class ModelArch:
    name: str
    role: str                       # "orchestrator" | "coder"
    quant: str
    weights_gib: float
    layers: int
    attention: str                  # "gqa" | "mha" | "mla"
    n_kv_heads: int = 0
    head_dim: int = 0
    mla_kv_lora: int = 0
    mla_rope: int = 0
    native_ctx: int = 8192
    verified: bool = False          # architecture confirmed from a public model card
    expected_slots_8k: int | None = None   # blueprint's stated figure, for cross-check
    scenario: str = ""

    def kv_bytes_per_token(self, dtype_bytes: int = KV_DTYPE_BYTES) -> int:
        if self.attention == "mla":
            return self.layers * (self.mla_kv_lora + self.mla_rope) * dtype_bytes
        return 2 * self.layers * self.n_kv_heads * self.head_dim * dtype_bytes

    def slot_gib(self, ctx: int = 8192, dtype_bytes: int = KV_DTYPE_BYTES) -> float:
        return self.kv_bytes_per_token(dtype_bytes) * ctx / GiB

    def max_slots(self, ctx: int = 8192, vram: float = VRAM_GIB,
                  overhead: float = OVERHEAD_GIB) -> int:
        avail = vram - self.weights_gib - overhead
        s = self.slot_gib(ctx)
        return max(0, int(avail // s)) if s > 0 else 0

    def fits_single(self, ctx: int = 8192, vram: float = VRAM_GIB,
                    overhead: float = OVERHEAD_GIB) -> bool:
        return self.weights_gib + overhead + self.slot_gib(ctx) <= vram

    def max_ctx_fp16(self, vram: float = VRAM_GIB, overhead: float = OVERHEAD_GIB) -> int:
        avail = (vram - self.weights_gib - overhead) * GiB
        per_tok = self.kv_bytes_per_token()
        return int(avail // per_tok) if per_tok > 0 else 0


# ─────────────────────────────────────────────────────────────────────────────
# Architecture table. VERIFIED entries use published configs (Qwen2.5 / DeepSeek-V2);
# UNVERIFIED entries (newer/2026 MoE) use representative values pending model-card
# confirmation — the blueprint itself flags these as "verify before deployment".
# ─────────────────────────────────────────────────────────────────────────────
MODELS: list[ModelArch] = [
    ModelArch(
        name="Qwen3.6-35B-A3B", role="orchestrator", quant="Q4", weights_gib=18.0,
        layers=48, attention="gqa", n_kv_heads=8, head_dim=128,
        native_ctx=262144, verified=False,
    ),
    ModelArch(
        name="Qwen3-Coder-30B-A3B", role="coder", scenario="A", quant="Q4_K_M",
        weights_gib=19.0, layers=48, attention="gqa", n_kv_heads=4, head_dim=128,
        native_ctx=262144, verified=False, expected_slots_8k=4,
    ),
    ModelArch(
        name="DeepSeek-Coder-V2-Lite-16B", role="coder", scenario="B", quant="Q4",
        weights_gib=9.0, layers=27, attention="mla", mla_kv_lora=512, mla_rope=64,
        native_ctx=163840, verified=True, expected_slots_8k=57,
    ),
    ModelArch(
        name="Qwen2.5-Coder-14B-Instruct", role="coder", quant="Q4_K_M",
        weights_gib=9.5, layers=48, attention="gqa", n_kv_heads=8, head_dim=128,
        native_ctx=131072, verified=True, expected_slots_8k=9,
    ),
    ModelArch(
        name="Qwen2.5-Coder-7B-Instruct", role="coder", quant="Q4_K_M",
        weights_gib=4.5, layers=28, attention="gqa", n_kv_heads=4, head_dim=128,
        native_ctx=131072, verified=True, expected_slots_8k=41,
    ),
]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class ResourceReport:
    orchestrator: dict
    coders: list[dict]
    ram: dict
    swap: dict
    checks: list[Check] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _orch_report(m: ModelArch) -> dict:
    kv_budget = VRAM_GIB - m.weights_gib - OVERHEAD_GIB
    max_ctx = m.max_ctx_fp16()
    return {
        "name": m.name, "quant": m.quant, "weights_gib": m.weights_gib,
        "overhead_gib": OVERHEAD_GIB, "kv_budget_gib": round(kv_budget, 2),
        "kv_kb_per_token": round(m.kv_bytes_per_token() / 1024, 2),
        "max_ctx_fp16": max_ctx, "native_ctx": m.native_ctx,
        "fits_single_8k": m.fits_single(8192), "verified": m.verified,
    }


def _coder_report(m: ModelArch) -> dict:
    return {
        "name": m.name, "scenario": m.scenario, "quant": m.quant,
        "attention": m.attention, "weights_gib": m.weights_gib,
        "kv_kb_per_token": round(m.kv_bytes_per_token() / 1024, 2),
        "slot_gib_8k": round(m.slot_gib(8192), 3),
        "max_slots_8k": m.max_slots(8192), "fits_single_8k": m.fits_single(8192),
        "expected_slots_8k": m.expected_slots_8k, "verified": m.verified,
    }


def validate() -> ResourceReport:
    orch = next(m for m in MODELS if m.role == "orchestrator")
    coders = [m for m in MODELS if m.role == "coder"]

    o = _orch_report(orch)
    crs = [_coder_report(m) for m in coders]

    scen_a = next(m for m in coders if m.scenario == "A")
    scen_b = next(m for m in coders if m.scenario == "B")
    both_weights = orch.weights_gib + scen_a.weights_gib
    ram = {
        "os_gib": OS_GIB,
        "both_weights_gib": round(both_weights, 1),
        "page_cache_free_gib": round(RAM_GIB - OS_GIB - both_weights, 1),
        "fits": OS_GIB + both_weights <= RAM_GIB,
    }
    swap = {
        "orchestrator_gib": orch.weights_gib,
        "coder_gib": scen_a.weights_gib,
        "orch_load_s": round(orch.weights_gib / 20.0, 2),
        "coder_load_s": round(scen_a.weights_gib / 20.0, 2),
    }

    checks: list[Check] = []
    checks.append(Check(
        "orchestrator fits single-resident (24GB)", o["fits_single_8k"],
        f"{orch.name}: {orch.weights_gib}+{OVERHEAD_GIB}+KV(8K) ≤ 24GB",
    ))
    for m in coders:
        checks.append(Check(
            f"coder fits single-resident: {m.name}", m.fits_single(8192),
            f"weights {m.weights_gib} + overhead {OVERHEAD_GIB} + 1×8K slot "
            f"{m.slot_gib(8192):.2f} = {m.weights_gib + OVERHEAD_GIB + m.slot_gib(8192):.2f}GB",
        ))
    for m in coders:
        if m.expected_slots_8k is None:
            continue
        got = m.max_slots(8192)
        exp = m.expected_slots_8k
        # methodology check: computed reproduces blueprint within ±35%
        ok = abs(got - exp) <= max(2, 0.35 * exp)
        checks.append(Check(
            f"KV math reproduces blueprint slots: {m.name}", ok,
            f"computed {got} vs blueprint {exp} (8K, fp16 KV)"
            + ("" if m.verified else "  [arch unverified]"),
        ))
    checks.append(Check(
        "both model weights fit warm in RAM page cache (64GB)", ram["fits"],
        f"OS {OS_GIB} + weights {ram['both_weights_gib']} ≤ 64GB "
        f"(free {ram['page_cache_free_gib']}GB)",
    ))
    checks.append(Check(
        "no offloading needed (both single-resident in 24GB)",
        o["fits_single_8k"] and scen_a.fits_single(8192),
        "sequential-swap holds: each phase's model owns 24GB alone",
    ))

    return ResourceReport(orchestrator=o, coders=crs, ram=ram, swap=swap, checks=checks)


def format_report(r: ResourceReport) -> str:
    L: list[str] = []
    L.append("RESOURCE VALIDATION · RTX 4090 24GB / 64GB (no hardware — computed)")
    L.append("=" * 70)
    o = r.orchestrator
    L.append(f"\nOrchestrator (Phase A) · {o['name']} [{o['quant']}]"
             + ("" if o["verified"] else "  (arch unverified)"))
    L.append(f"  weights {o['weights_gib']}GB + overhead {o['overhead_gib']}GB "
             f"→ KV budget {o['kv_budget_gib']}GB")
    L.append(f"  KV {o['kv_kb_per_token']} KB/token → max fp16 context "
             f"{o['max_ctx_fp16']:,} tok (native claim {o['native_ctx']:,})")
    if o["max_ctx_fp16"] < o["native_ctx"]:
        L.append(f"  ⚠ full {o['native_ctx']:,}-tok context needs KV quantization "
                 f"(Q8≈2×, Q4≈4× the fp16 ctx); non-design modes stay ≤8K by design")

    L.append("\nCoders (Phase B) · slots @ 8K ctx, fp16 KV:")
    L.append(f"  {'model':<32}{'attn':<5}{'wt':>5}{'KB/tok':>8}{'GB/slot':>9}{'slots':>7}{'blueprint':>10}")
    for c in r.coders:
        exp = "-" if c["expected_slots_8k"] is None else str(c["expected_slots_8k"])
        star = "" if c["verified"] else "*"
        L.append(f"  {c['name'][:31]:<32}{c['attention']:<5}{c['weights_gib']:>5}"
                 f"{c['kv_kb_per_token']:>8}{c['slot_gib_8k']:>9}{c['max_slots_8k']:>7}{exp:>10}{star}")
    L.append("  (* architecture unverified — same methodology, confirm on model card)")

    L.append(f"\nSystem DRAM (64GB): OS {r.ram['os_gib']}GB + both weights "
             f"{r.ram['both_weights_gib']}GB → {r.ram['page_cache_free_gib']}GB free for warm cache")
    L.append(f"Swap cost (warm cache, ~20GB/s): orch ~{r.swap['orch_load_s']}s · "
             f"coder ~{r.swap['coder_load_s']}s")

    L.append("\nChecks:")
    for c in r.checks:
        L.append(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}")
        L.append(f"         {c.detail}")
    L.append(f"\n{'ALL RESOURCE CHECKS PASS' if r.all_ok else 'SOME CHECKS FAILED'} "
             f"({sum(c.ok for c in r.checks)}/{len(r.checks)})")
    return "\n".join(L)
