"""Execution sandbox for the Synthesizer/Review nodes.

* ``LocalSandbox``  — subprocess with cwd pinned to the workspace (fast).
* ``DockerSandbox`` — runs the command inside a container with ONLY the workspace
                      mounted (recommended; add ``--runtime=runsc`` for gVisor).

Both return ``(exit_code, combined_output)``. Docker falls back to a clear error
report (not an exception) if the daemon/image is unavailable, so a run never dies
on infrastructure.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


def _split(cmd: str) -> list[str]:
    # POSIX-style splitting works for our commands on Windows too.
    parts = shlex.split(cmd, posix=True)
    # Let bare "python" resolve to the interpreter running CLID.
    if parts and parts[0] == "python":
        parts[0] = sys.executable
    return parts


class Sandbox:
    def run(self, workspace: Path, cmd: str, timeout: float = 120.0) -> tuple[int, str]:
        raise NotImplementedError


class LocalSandbox:
    name = "local"

    def run(self, workspace: Path, cmd: str, timeout: float = 120.0) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                _split(cmd),
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as e:
            return 127, f"command not found: {e}"
        except subprocess.TimeoutExpired:
            return 124, f"timeout after {timeout}s: {cmd}"
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class DockerSandbox:
    name = "docker"

    def __init__(self, image: str = "python:3.12-slim", runtime: str | None = None) -> None:
        self.image = image
        self.runtime = runtime  # e.g. "runsc" for gVisor

    def run(self, workspace: Path, cmd: str, timeout: float = 300.0) -> tuple[int, str]:
        docker_cmd = ["docker", "run", "--rm", "--network", "none",
                      "-v", f"{workspace}:/w", "-w", "/w"]
        if self.runtime:
            docker_cmd += ["--runtime", self.runtime]
        docker_cmd += [self.image, "sh", "-lc", cmd]
        try:
            proc = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return 127, "docker not found on PATH; set CLID_SANDBOX=local or install Docker"
        except subprocess.TimeoutExpired:
            return 124, f"docker timeout after {timeout}s"
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def get_sandbox(kind: str) -> Sandbox:
    if kind == "docker":
        return DockerSandbox()
    return LocalSandbox()
