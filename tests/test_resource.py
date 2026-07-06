"""Resource-model validation (hardware-free)."""

import unittest

from clid.resource import MODELS, ModelArch, validate


class TestResourceModel(unittest.TestCase):
    def test_all_checks_pass(self):
        r = validate()
        failed = [c.name for c in r.checks if not c.ok]
        self.assertTrue(r.all_ok, f"failed checks: {failed}")

    def test_every_intended_model_fits_single_resident(self):
        for m in MODELS:
            self.assertTrue(m.fits_single(8192), f"{m.name} does not fit in 24GB at 8K")

    def test_mla_kv_formula(self):
        ds = next(m for m in MODELS if m.attention == "mla")
        # MLA stores a single compressed latent: layers · (kv_lora + rope) · 2 bytes
        self.assertEqual(ds.kv_bytes_per_token(), ds.layers * (ds.mla_kv_lora + ds.mla_rope) * 2)

    def test_gqa_kv_formula(self):
        q14 = next(m for m in MODELS if m.name.startswith("Qwen2.5-Coder-14B"))
        self.assertEqual(q14.kv_bytes_per_token(), 2 * q14.layers * q14.n_kv_heads * q14.head_dim * 2)

    def test_kv_math_reproduces_blueprint(self):
        for m in MODELS:
            if m.expected_slots_8k is None:
                continue
            got = m.max_slots(8192)
            self.assertLessEqual(
                abs(got - m.expected_slots_8k), max(2, 0.35 * m.expected_slots_8k),
                f"{m.name}: computed {got} vs blueprint {m.expected_slots_8k}",
            )

    def test_mla_gives_far_more_slots_than_gqa(self):
        ds = next(m for m in MODELS if m.attention == "mla")
        q14 = next(m for m in MODELS if m.name.startswith("Qwen2.5-Coder-14B"))
        self.assertGreater(ds.max_slots(8192), 5 * q14.max_slots(8192))

    def test_orchestrator_fits_8k_but_not_full_native_context_in_fp16(self):
        orch = next(m for m in MODELS if m.role == "orchestrator")
        self.assertGreaterEqual(orch.max_ctx_fp16(), 8192)      # 8K modes fit
        self.assertLess(orch.max_ctx_fp16(), orch.native_ctx)   # 262K needs KV quant


if __name__ == "__main__":
    unittest.main()
