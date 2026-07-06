"""Deterministic build/test runners — the objective half of Hybrid Review.

Tools decide pass/fail; the Orchestrator only diagnoses failures. Kept
language-agnostic at the seams but ships a Python path (py_compile + the design's
test command) that needs zero third-party packages.
"""

from __future__ import annotations

import compileall
import io
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import Sandbox


@dataclass
class ToolReport:
    compiled: bool = True
    compile_output: str = ""
    tests_ran: bool = False
    tests_passed: bool = False
    test_output: str = ""
    install_output: str = ""

    @property
    def ok(self) -> bool:
        return self.compiled and (not self.tests_ran or self.tests_passed)

    def summary(self) -> str:
        bits = [f"compile={'ok' if self.compiled else 'FAIL'}"]
        if self.tests_ran:
            bits.append(f"tests={'pass' if self.tests_passed else 'FAIL'}")
        return " ".join(bits)

    def failure_text(self) -> str:
        if not self.compiled:
            return self.compile_output
        if self.tests_ran and not self.tests_passed:
            return self.test_output
        return ""


def compile_python(workspace: Path) -> tuple[bool, str]:
    """py_compile every .py under the workspace. Returns (ok, output)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = compileall.compile_dir(str(workspace), quiet=1, force=True)
    return bool(ok), buf.getvalue().strip()


def run_install(sandbox: Sandbox, workspace: Path, install_cmd: str) -> str:
    if not install_cmd.strip():
        return ""
    _code, out = sandbox.run(workspace, install_cmd, timeout=300.0)
    return out


def run_tests(sandbox: Sandbox, workspace: Path, test_cmd: str) -> tuple[bool, str]:
    if not test_cmd.strip():
        return False, "(no test command)"
    code, out = sandbox.run(workspace, test_cmd, timeout=180.0)
    return code == 0, out


def review(sandbox: Sandbox, workspace: Path, *, install_cmd: str = "",
           test_cmd: str = "") -> ToolReport:
    """Full deterministic pass: install → compile → test."""
    report = ToolReport()
    report.install_output = run_install(sandbox, workspace, install_cmd)
    report.compiled, report.compile_output = compile_python(workspace)
    if not report.compiled:
        return report
    if test_cmd.strip():
        report.tests_ran = True
        report.tests_passed, report.test_output = run_tests(sandbox, workspace, test_cmd)
    return report
