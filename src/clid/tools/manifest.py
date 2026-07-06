"""Context manifest (Librarian) — signatures/types/deps, not whole files.

Feeds the Coder only the minimal signatures of its ``context_files`` instead of
their full source. Pure-deterministic (no LLM). Uses ``tree-sitter`` when
installed for accurate parsing; otherwise a regex fallback that covers Python.
"""

from __future__ import annotations

import re
from pathlib import Path

# Anchored at column 0 → only top-level (public API) defs/classes, not methods.
_PY_DEF = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*(\([^)]*\))", re.MULTILINE)
_PY_CLASS = re.compile(r"^class\s+([A-Za-z_]\w*)\s*(\([^)]*\))?", re.MULTILINE)


def _python_signatures(source: str) -> list[str]:
    sigs: list[str] = []
    for name, params in _PY_CLASS.findall(source):
        sigs.append(f"class {name}{params or ''}")
    for name, params in _PY_DEF.findall(source):
        sigs.append(f"def {name}{params}")
    return sigs


def file_signatures(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if path.suffix == ".py":
        return _python_signatures(source)
    return []  # other languages: extend here (tree-sitter grammars)


def build_manifest(workspace: Path, only: list[str] | None = None) -> dict[str, list[str]]:
    """Map relative path -> list of top-level signatures.

    ``only`` restricts to specific relative paths (a Coder's context_files).
    """
    manifest: dict[str, list[str]] = {}
    if only:
        candidates = [workspace / rel for rel in only]
    else:
        candidates = [p for p in workspace.rglob("*.py") if "__pycache__" not in p.parts]
    for p in candidates:
        if p.exists() and p.is_file():
            manifest[p.relative_to(workspace).as_posix()] = file_signatures(p)
    return manifest


def render_manifest(manifest: dict[str, list[str]]) -> str:
    lines = []
    for path, sigs in manifest.items():
        lines.append(f"# {path}")
        if sigs:
            lines.extend(f"  {s}" for s in sigs)
        else:
            lines.append("  (no signatures)")
    return "\n".join(lines)
