"""Deterministic template engine — the "Triage → template" efficiency layer.

Boilerplate files (``route == "template"``) are emitted here WITHOUT a Coder
call, saving generation for real logic. Package ``__init__.py`` files are built
by re-exporting the public signatures of sibling modules (via the manifest), so
they stay correct with zero model involvement.
"""

from __future__ import annotations

import posixpath

from ..schemas import Design
from .manifest import file_signatures
from .workspace import Workspace


def render_template(path: str, design: Design, ws: Workspace) -> str:
    base = posixpath.basename(path).lower()
    if base == "__init__.py":
        return _render_init(path, ws)
    if base == "readme.md":
        return _render_readme(design)
    return f"# {path}\n"


def _render_init(path: str, ws: Workspace) -> str:
    pkg_dir = posixpath.dirname(path)
    exports: list[tuple[str, list[str]]] = []
    for rel in ws.list_files():
        if posixpath.dirname(rel) != pkg_dir:
            continue
        if not rel.endswith(".py") or posixpath.basename(rel) == "__init__.py":
            continue
        mod = posixpath.basename(rel)[:-3]
        funcs = [
            s[len("def "):].split("(")[0].strip()
            for s in file_signatures(ws.root / rel)
            if s.startswith("def ") and not s[len("def "):].startswith("_")
        ]
        if funcs:
            exports.append((mod, funcs))

    lines = ['"""Package init (templated — no Coder call)."""', ""]
    all_names: list[str] = []
    for mod, funcs in exports:
        lines.append(f"from .{mod} import " + ", ".join(funcs))
        all_names.extend(funcs)
    if all_names:
        lines.append("")
        lines.append("__all__ = [" + ", ".join(f'"{n}"' for n in all_names) + "]")
    return "\n".join(lines) + "\n"


def _render_readme(design: Design) -> str:
    parts = [f"# {design.root}", ""]
    if design.notes:
        parts += [design.notes, ""]
    if design.build.test:
        parts += ["## Build", "", f"- test: `{design.build.test}`"]
        if design.build.entrypoint:
            parts.append(f"- run: `{design.build.entrypoint}`")
        parts.append("")
    return "\n".join(parts)
