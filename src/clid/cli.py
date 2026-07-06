"""CLID command-line entrypoint.

    python -m clid.cli "Build a Python calculator library with tests"
    python -m clid.cli --demo-bug "calculator library"   # exercise the L1 loop
    python -m clid.cli --list-runs
    python -m clid.cli --show-run <run_id>
"""

from __future__ import annotations

# Allow running as `python src/clid/cli.py` as well as `python -m clid.cli`.
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import argparse
import json
import time

from clid.config import get_settings


def _new_run_id(request: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = f"{abs(hash(request)) % 0x10000:04x}"
    return f"{stamp}-{tag}"


def _live_printer():
    """Return an on_step callback that prints only newly-appended log lines."""
    seen = {"n": 0}

    def on_step(_node: str, state: dict) -> None:
        log = state.get("log", [])
        for line in log[seen["n"]:]:
            print(f"  {line}")
        seen["n"] = len(log)

    return on_step


def cmd_run(args: argparse.Namespace) -> int:
    from clid.graph.pipeline import Pipeline

    settings = get_settings()
    if args.backend:
        import os
        os.environ["CLID_BACKEND"] = args.backend
        get_settings.cache_clear()  # type: ignore[attr-defined]
        settings = get_settings()

    run_id = _new_run_id(args.request)
    print(f"● CLID run {run_id}")
    print(f"  backend={settings.backend} · strategy={settings.strategy_mode} · sandbox={settings.sandbox}")
    print(f"  request: {args.request}\n")

    pipe = Pipeline(settings, run_id)
    on_step = None if args.quiet else _live_printer()
    final = pipe.run(args.request, demo_bug=args.demo_bug, on_step=on_step)

    result = final.get("result", {})
    print()
    if final.get("status") == "done":
        print(f"✓ {result.get('status')} — {len(result.get('files', []))} files in {result.get('workspace')}")
        for f in result.get("files", []):
            print(f"    {f}")
        print(f"  tests_passed={result.get('tests_passed')} · iterations={result.get('iterations')} "
              f"· swaps={result.get('swaps')}")
        print(f"  build.test: {result.get('build', {}).get('test', '')}")
    else:
        print(f"✗ halted — {result.get('reason')}")
        return 1
    print(f"\n  run dir: {settings.runs_dir / run_id}")
    return 0


def cmd_list_runs(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.runs_dir.exists():
        print("(no runs yet)")
        return 0
    runs = sorted(p.name for p in settings.runs_dir.iterdir() if p.is_dir())
    for r in runs:
        latest = settings.runs_dir / r / "latest.json"
        status = "?"
        if latest.exists():
            try:
                status = json.loads(latest.read_text(encoding="utf-8")).get("status", "?")
            except json.JSONDecodeError:
                pass
        print(f"  {r}  [{status}]")
    print(f"\n{len(runs)} run(s) in {settings.runs_dir}")
    return 0


def cmd_show_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    latest = settings.runs_dir / args.run_id / "latest.json"
    if not latest.exists():
        print(f"no such run: {args.run_id}")
        return 1
    state = json.loads(latest.read_text(encoding="utf-8"))
    print(f"● run {args.run_id} — status={state.get('status')}")
    print("\n  log:")
    for line in state.get("log", []):
        print(f"    {line}")
    print("\n  result:")
    print(json.dumps(state.get("result", {}), indent=2, ensure_ascii=False))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Hardware-free verification: resource model + functional self-checks."""
    import os
    import tempfile
    from pathlib import Path

    from clid.resource import format_report, validate

    report = validate()
    print(format_report(report))

    # Functional self-checks always run on the mock backend (offline).
    os.environ["CLID_BACKEND"] = "mock"
    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()
    from clid.graph.pipeline import Pipeline

    print("\n\nFUNCTIONAL SELF-CHECKS · mock backend, offline")
    print("=" * 70)
    fchecks: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        settings.workspaces_dir = Path(tmp) / "ws"
        settings.runs_dir = Path(tmp) / "runs"

        f1 = Pipeline(settings, "verify-clean").run("Build a Python calculator library with tests")
        fchecks.append((
            "clean run: 6 stages, PASS on first review, tests execute",
            f1["status"] == "done" and f1["result"]["tests_passed"] and f1["iterations"] == 0,
            f"status={f1['status']} tests={f1['result'].get('tests_passed')} iters={f1['iterations']} swaps={f1['result'].get('swaps')}",
        ))
        f2 = Pipeline(settings, "verify-bug").run("calculator library", demo_bug=True)
        fchecks.append((
            "L1 self-repair: injected bug fixed via exactly one rewrite loop",
            f2["status"] == "done" and f2["iterations"] == 1 and f2["result"]["tests_passed"],
            f"status={f2['status']} iters={f2['iterations']}",
        ))
        f3 = Pipeline(settings, "verify-generic").run("make a widget parser thing")
        fchecks.append((
            "generic fallback recipe completes green",
            f3["status"] == "done" and f3["result"]["tests_passed"],
            f"status={f3['status']}",
        ))

    for name, ok, detail in fchecks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")

    all_ok = report.all_ok and all(ok for _, ok, _ in fchecks)
    total = len(report.checks) + len(fchecks)
    passed = sum(c.ok for c in report.checks) + sum(ok for _, ok, _ in fchecks)

    print("\n\nREQUIRES PHYSICAL RTX 4090 (cannot be verified without hardware):")
    print("=" * 70)
    for item in (
        "actual decode throughput (tok/s) per model and quant",
        "true concurrent slot count under GPU-compute (not just memory) bottleneck",
        "real quantized-model output quality / SWE-bench pass rate",
        "measured warm-cache swap latency on your NVMe + PCIe",
        "KV-quantization quality trade-off at extended (>24K) context",
    ):
        print(f"  • {item}")

    print(f"\n{'='*70}")
    print(f"{'✓ VERIFICATION PASSED' if all_ok else '✗ VERIFICATION FAILED'} — {passed}/{total} checks")
    return 0 if all_ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clid", description="Local coding-agent orchestration.")
    p.add_argument("request", nargs="?", help="natural-language build request")
    p.add_argument("--backend", choices=["mock", "openai"], help="override CLID_BACKEND")
    p.add_argument("--demo-bug", action="store_true",
                   help="inject a bug on the first Coder attempt to exercise the L1 rewrite loop")
    p.add_argument("--quiet", action="store_true", help="suppress live stage logging")
    p.add_argument("--verify", action="store_true",
                   help="hardware-free verification: resource model + functional self-checks")
    p.add_argument("--list-runs", action="store_true", help="list previous runs")
    p.add_argument("--show-run", metavar="RUN_ID", help="show a previous run's log + result")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verify:
        return cmd_verify(args)
    if args.list_runs:
        return cmd_list_runs(args)
    if args.show_run:
        args.run_id = args.show_run
        return cmd_show_run(args)
    if not args.request:
        build_parser().print_help()
        return 2
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
