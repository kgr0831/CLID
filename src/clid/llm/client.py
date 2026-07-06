"""LLM client interface + two backends.

* ``MockLLM``          — deterministic, offline. Routes by ``mode`` into ``mockgen``.
* ``OpenAICompatLLM``  — talks to any OpenAI-compatible ``/chat/completions``
                          endpoint (llama.cpp server, ExLlamaV3+TabbyAPI).

Nodes never branch on backend: they call ``chat(mode=..., system=..., user=...,
context=...)`` and get back a dict (when ``expect_json``) or a string.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import mockgen


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating ```json fences / prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # last resort: grab the outermost {...} or [...]
        m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        raise LLMError(f"no JSON in response: {text[:200]!r}")


class LLMClient:
    name: str = "base"

    def chat(
        self,
        *,
        mode: str,
        system: str,
        user: str,
        context: dict | None = None,
        expect_json: bool = True,
        temperature: float = 0.2,
    ) -> Any:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
class MockLLM(LLMClient):
    """Offline backend. `role` distinguishes the Orchestrator from the Coder."""

    def __init__(self, role: str = "orchestrator") -> None:
        self.name = f"mock:{role}"
        self.role = role

    def chat(self, *, mode, system, user, context=None, expect_json=True, temperature=0.2):
        ctx = context or {}
        request = ctx.get("request", "")
        plan = mockgen.build_plan(request)

        if mode == "classify":
            return plan["classification"]
        if mode == "design":
            return plan["design"]
        if mode == "delegate":
            return self._delegate(plan)
        if mode == "coder":
            return self._coder(plan, ctx)
        if mode == "diagnose":
            return {"consistent": True, "issues": []}
        if mode == "judge":
            return self._judge(ctx)
        raise LLMError(f"unknown mode {mode!r}")

    def _delegate(self, plan: dict) -> dict:
        tasks = []
        for f in plan["design"]["files"]:
            route = "template" if f["role"] == "boilerplate" else "coder"
            specialization = {
                "test": "You are a test-harness engineer. Write thorough, deterministic tests.",
                "core_logic": "You are a systems implementer. Honor the exact contract.",
                "config": "You are a build/config specialist.",
                "boilerplate": "Scaffolding only.",
            }.get(f["role"], "You are a Coder.")
            tasks.append({
                "path": f["path"],
                "route": route,
                "system_prompt": specialization,
                "instructions": f["spec"],
                "context_files": f.get("depends_on", []),
                "acceptance": f"{f['path']} matches its spec and the suite passes.",
            })
        return {"tasks": tasks}

    def _coder(self, plan: dict, ctx: dict) -> dict:
        path = ctx.get("path", "")
        attempt = int(ctx.get("attempt", 0))
        demo_bug = bool(ctx.get("demo_bug", False))
        persist = bool(ctx.get("persist_fail", False))
        buggy = plan.get("files_buggy", {})
        good = plan["files_good"].get(path, f"# {path}\n")
        if persist and path in buggy:  # never converges — drives L2/L3/L4 escalation
            return {"path": path, "content": buggy[path],
                    "notes": "persistent-failure mode (always buggy)"}
        if demo_bug and attempt == 0 and path in buggy:
            return {"path": path, "content": buggy[path],
                    "notes": "initial attempt (demo bug: missing zero-guard)"}
        note = "applied correction (added zero-guard)" if attempt > 0 else "generated"
        return {"path": path, "content": good, "notes": note}

    def _judge(self, ctx: dict) -> dict:
        retries = ctx.get("retries", {})
        thr = ctx.get("thresholds", {})
        focus = ctx.get("focus_path", "")
        out = ctx.get("tool_output", "")
        if retries.get("rewrite", 0) < thr.get("rewrite_retries", 2):
            route, corr = "coder", "Fix the failing file per the test output."
        elif retries.get("redelegate", 0) < thr.get("redelegate_retries", 2):
            route, corr = "runner", "Re-decompose this file's build prompt."
        elif retries.get("redesign", 0) < thr.get("redesign_retries", 1):
            route, corr = "sub", "Redesign the interface; multiple files fail."
        else:
            route, corr = "halt", "Budget exhausted; requirements may be unsatisfiable."
        return {"verdict": "fail", "route": route, "target_path": focus,
                "reason": (out.splitlines()[-1] if out else "test failure"),
                "correction": corr}


# ─────────────────────────────────────────────────────────────────────────────
class OpenAICompatLLM(LLMClient):
    """OpenAI-compatible HTTP backend (llama.cpp `--server`, TabbyAPI, …)."""

    def __init__(self, base_url: str, model: str, api_key: str = "sk-local",
                 role: str = "orchestrator", timeout: float = 120.0) -> None:
        self.name = f"openai:{role}:{model}"
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def chat(self, *, mode, system, user, context=None, expect_json=True, temperature=0.2):
        import httpx  # imported lazily so `mock` mode needs nothing

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if expect_json:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions", json=payload,
                              headers=headers, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"{self.name}: request failed: {e}") from e
        content = resp.json()["choices"][0]["message"]["content"]
        return extract_json(content) if expect_json else content
