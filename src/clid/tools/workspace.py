"""Workspace — the on-disk project the Coder writes into.

Path writes are confined to the workspace root (no traversal), so a Coder can
never escape its mounted directory — the deterministic half of the sandbox story.
"""

from __future__ import annotations

from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, rel: str) -> Path:
        target = (self.root / rel).resolve()
        if target != self.root and self.root not in target.parents:
            raise WorkspaceError(f"path escapes workspace: {rel!r}")
        return target

    def write(self, rel: str, content: str) -> Path:
        target = self._safe(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def read(self, rel: str) -> str:
        return self._safe(rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        return self._safe(rel).exists()

    def list_files(self) -> list[str]:
        out = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                out.append(p.relative_to(self.root).as_posix())
        return out
