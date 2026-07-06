"""The CLID pipeline: six logical stages wired as a DAG with feedback loops.

Stages (physical executor in brackets):
  1 classify   [Orchestrator·classify]
  2 design     [Orchestrator·design]
  3 delegate   [Orchestrator·delegate]
  4 code       [Coder  +  Templater for boilerplate]
  5 synthesize [tools: install/compile  +  Orchestrator·diagnose]
  6 review     [tools: test  +  Orchestrator·judge on failure]  → routes:
        pass       → finalize
        rewrite L1 → code       (same Coder fixes the focus file)
        redelegate L2 → delegate
        redesign  L3 → design
        halt      L4 → halt

The whole thing runs under sequential-swap: Phase A nodes hold the Orchestrator,
the ``code`` node swaps the Coder in, and ``synthesize`` swaps the Orchestrator back.
"""

from __future__ import annotations

from ..coder import Coder
from ..config import Settings
from ..llm import SequentialSwapManager, SwapEvent
from ..orchestrator import Orchestrator
from ..schemas import Classification, Delegation, Design
from ..tools import Workspace, get_sandbox, review as tool_review
from ..tools.runners import run_tests
from ..tools.templater import render_template
from .checkpoint import JSONCheckpointer
from .engine import END, START, StateGraph
from .state import REDUCERS, new_state


class Pipeline:
    def __init__(self, settings: Settings, run_id: str) -> None:
        self.settings = settings
        self.run_id = run_id
        self.manager = SequentialSwapManager(settings)
        self.orch = Orchestrator(self.manager, settings)
        self.coder = Coder(self.manager, settings)
        self.sandbox = get_sandbox(settings.sandbox)
        self.ws = Workspace(settings.workspaces_dir / run_id)
        rv = settings.review
        self.thresholds = {
            "rewrite_retries": rv.get("rewrite_retries", 2),
            "redelegate_retries": rv.get("redelegate_retries", 2),
            "redesign_retries": rv.get("redesign_retries", 1),
            "global_budget_iters": rv.get("global_budget_iters", 12),
        }

    # ── helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _swap_logs(swap: SwapEvent | None) -> list[str]:
        return [f"   ⇄ {swap.note}"] if swap else []

    def _pick_focus(self, state: dict, design: Design, output: str) -> str:
        core = [f.path for f in design.files if f.role == "core_logic"]
        for path in core:
            if path and path in output:
                return path
        if core:
            return core[0]
        dele = Delegation(**state.get("delegation", {"tasks": []}))
        coder_tasks = [t.path for t in dele.tasks if t.route == "coder"]
        return coder_tasks[0] if coder_tasks else ""

    # ── 1 · classify ─────────────────────────────────────────────────────
    def classify(self, s: dict) -> dict:
        cls, swap = self.orch.classify(s["request"])
        logs = self._swap_logs(swap)
        logs.append(f"1·classify → {cls.domain}/{cls.project_type} (conf {cls.confidence:.2f})")
        return {"classification": cls.model_dump(), "phase": "A", "log": logs}

    # ── 2 · design ───────────────────────────────────────────────────────
    def design(self, s: dict) -> dict:
        cls = Classification(**s["classification"])
        d, swap = self.orch.design(s["request"], cls)
        retries = dict(s["retries"]); retries["rewrite"] = 0; retries["redelegate"] = 0
        logs = self._swap_logs(swap)
        logs.append(f"2·design → {len(d.files)} files, root={d.root}")
        return {"design": d.model_dump(), "retries": retries, "focus_path": "", "log": logs}

    # ── 3 · delegate ─────────────────────────────────────────────────────
    def delegate(self, s: dict) -> dict:
        d = Design(**s["design"])
        dele, swap = self.orch.delegate(s["request"], d)
        n_tpl = sum(1 for t in dele.tasks if t.route == "template")
        retries = dict(s["retries"]); retries["rewrite"] = 0
        logs = self._swap_logs(swap)
        logs.append(f"3·delegate → {len(dele.tasks)} tasks ({n_tpl} templated, {len(dele.tasks) - n_tpl} coder)")
        return {"delegation": dele.model_dump(), "retries": retries, "focus_path": "", "log": logs}

    # ── 4 · code ─────────────────────────────────────────────────────────
    def code(self, s: dict) -> dict:
        dele = Delegation(**s["delegation"])
        design = Design(**s["design"])
        files = dict(s.get("files") or {})
        demo_bug = bool(s.get("demo_bug", False))
        persist_fail = bool(s.get("persist_fail", False))
        focus = s.get("focus_path", "")
        logs: list[str] = []

        if focus:  # ── L1 rewrite: regenerate just the focus file
            task = next((t for t in dele.tasks if t.path == focus and t.route == "coder"), None)
            if task is None:
                logs.append(f"4·code rewrite skipped (no coder task for {focus})")
            else:
                attempt = s["retries"]["rewrite"]
                out, swap = self.coder.generate(
                    s["request"], task, attempt=attempt, demo_bug=demo_bug,
                    persist_fail=persist_fail, correction=s.get("_correction", ""),
                )
                self.ws.write(out.path, out.content)
                files[out.path] = out.content
                logs += self._swap_logs(swap)
                logs.append(f"4·code rewrite {focus} (attempt {attempt}) — {out.notes}")
            return {"files": files, "phase": "B", "log": logs}

        # ── full generation pass
        coder_tasks = [t for t in dele.tasks if t.route == "coder"]
        tpl_tasks = [t for t in dele.tasks if t.route == "template"]
        swap_logged = False
        for t in coder_tasks:
            out, swap = self.coder.generate(s["request"], t, attempt=0,
                                            demo_bug=demo_bug, persist_fail=persist_fail)
            if swap and not swap_logged:
                logs += self._swap_logs(swap); swap_logged = True
            self.ws.write(out.path, out.content)
            files[out.path] = out.content
        for t in tpl_tasks:  # Triage → template: no Coder call
            content = render_template(t.path, design, self.ws)
            self.ws.write(t.path, content)
            files[t.path] = content
        logs.append(f"4·code → {len(coder_tasks)} generated, {len(tpl_tasks)} templated")
        return {"files": files, "phase": "B", "log": logs}

    # ── 5 · synthesize ───────────────────────────────────────────────────
    def synthesize(self, s: dict) -> dict:
        d = Design(**s["design"])
        report = tool_review(self.sandbox, self.ws.root, install_cmd=d.build.install, test_cmd="")
        diag, swap = self.orch.diagnose(s["request"], report.compile_output or report.summary())
        logs = self._swap_logs(swap)
        logs.append(f"5·synthesize → compile={'ok' if report.compiled else 'FAIL'}, consistent={diag.consistent}")
        return {
            "diagnosis": diag.model_dump(),
            "_compile_ok": report.compiled,
            "_compile_out": report.compile_output,
            "log": logs,
        }

    # ── 6 · review (routing point for both feedback loops) ───────────────
    def review(self, s: dict) -> dict:
        d = Design(**s["design"])
        compile_ok = s.get("_compile_ok", True)
        if compile_ok:
            passed, out = run_tests(self.sandbox, self.ws.root, d.build.test)
        else:
            passed, out = False, s.get("_compile_out", "compile failed")
        ok = compile_ok and passed
        review = {"passed": ok, "compiled": compile_ok, "test_output": out[-2000:]}

        if ok:
            return {"review": review, "route": "pass", "status": "running",
                    "log": [f"6·review → PASS ({d.build.test or 'no tests'})"]}

        iters = s.get("iterations", 0) + 1
        if iters > self.thresholds["global_budget_iters"]:
            return {"review": review, "route": "halt", "iterations": iters,
                    "_halt_reason": f"global budget {iters} exceeded",
                    "log": [f"6·review → FAIL, budget exceeded → HALT"]}

        focus = self._pick_focus(s, d, out)
        verdict, swap = self.orch.judge(
            s["request"], tool_output=out, focus_path=focus,
            retries=s["retries"], thresholds=self.thresholds,
        )
        route_key, updates = self._apply_route(s, verdict, focus)
        logs = self._swap_logs(swap)
        logs.append(f"6·review → FAIL → judge route={verdict.route}→{route_key} "
                    f"target={updates.get('focus_path') or focus}")
        return {
            "review": review, "route": route_key, "iterations": iters,
            "focus_path": updates.get("focus_path", ""),
            "retries": updates["retries"], "_correction": verdict.correction, "log": logs,
        }

    def _apply_route(self, s: dict, verdict, focus: str) -> tuple[str, dict]:
        retries = dict(s["retries"])
        r = verdict.route
        if r == "coder":
            retries["rewrite"] += 1
            return "rewrite", {"retries": retries, "focus_path": verdict.target_path or focus}
        if r == "runner":
            retries["redelegate"] += 1; retries["rewrite"] = 0
            return "redelegate", {"retries": retries, "focus_path": ""}
        if r == "sub":
            retries["redesign"] += 1; retries["rewrite"] = 0; retries["redelegate"] = 0
            return "redesign", {"retries": retries, "focus_path": ""}
        return "halt", {"retries": retries, "focus_path": ""}

    # ── terminal nodes ───────────────────────────────────────────────────
    def finalize(self, s: dict) -> dict:
        d = Design(**s["design"])
        result = {
            "status": "done",
            "root": d.root,
            "workspace": str(self.ws.root),
            "files": self.ws.list_files(),
            "build": d.build.model_dump(),
            "tests_passed": s.get("review", {}).get("passed"),
            "iterations": s.get("iterations", 0),
            "swaps": len(self.manager.swaps),
        }
        return {"result": result, "status": "done",
                "log": [f"✓ done · {len(result['files'])} files · "
                        f"tests={result['tests_passed']} · swaps={result['swaps']}"]}

    def halt(self, s: dict) -> dict:
        result = {
            "status": "halted",
            "reason": s.get("_halt_reason", "unsatisfiable"),
            "workspace": str(self.ws.root),
            "files": self.ws.list_files(),
            "iterations": s.get("iterations", 0),
        }
        return {"result": result, "status": "halted",
                "log": [f"✗ halted · {result['reason']}"]}

    # ── assembly ─────────────────────────────────────────────────────────
    def build_graph(self):
        g = StateGraph(reducers=REDUCERS)
        g.add_node("classify", self.classify)
        g.add_node("design", self.design)
        g.add_node("delegate", self.delegate)
        g.add_node("code", self.code)
        g.add_node("synthesize", self.synthesize)
        g.add_node("review", self.review)
        g.add_node("finalize", self.finalize)
        g.add_node("halt", self.halt)

        g.add_edge(START, "classify")
        g.add_edge("classify", "design")
        g.add_edge("design", "delegate")
        g.add_edge("delegate", "code")
        g.add_edge("code", "synthesize")
        g.add_edge("synthesize", "review")
        g.add_conditional_edges("review", lambda s: s["route"], {
            "pass": "finalize",
            "rewrite": "code",
            "redelegate": "delegate",
            "redesign": "design",
            "halt": "halt",
        })
        g.add_edge("finalize", END)
        g.add_edge("halt", END)
        return g.compile(checkpointer=JSONCheckpointer(self.settings.runs_dir), max_steps=200)

    def run(self, request: str, *, demo_bug: bool = False,
            persist_fail: bool = False, on_step=None) -> dict:
        state = new_state(request, str(self.ws.root), self.run_id)
        state["demo_bug"] = demo_bug
        state["persist_fail"] = persist_fail
        compiled = self.build_graph()
        return compiled.invoke(state, {"thread_id": self.run_id, "on_step": on_step})
