"""Deterministic mock generator.

The mock backend must let the *whole* pipeline run offline — including the
review loop that genuinely compiles and tests generated code. So this module
emits a real, runnable project derived from the request. Two recipes:

* ``calculator``    — a proper Python package with unittest tests (headline demo).
* ``python_module`` — a minimal but valid fallback for any other request.

Everything is a pure function of the request string, so each orchestrator mode
independently computes a *consistent* plan without shared state.

A demo bug can be injected (``demo_bug=True``) so the first Coder attempt on the
core file fails tests — exercising the L1 rewrite loop — and the rewrite fixes it.
"""

from __future__ import annotations

import re


def _slug(text: str) -> str:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", text.lower())
    for w in words:
        if w not in {"a", "an", "the", "build", "create", "make", "write", "with", "and", "in", "for"}:
            return w
    return "app"


def choose_recipe(request: str) -> str:
    r = request.lower()
    if any(k in r for k in ("calculator", "calc", "arithmetic", "add", "subtract", "multiply", "divide")):
        return "calculator"
    return "python_module"


# ─────────────────────────────────────────────────────────────────────────────
# Recipe: calculator
# ─────────────────────────────────────────────────────────────────────────────
_CALC_OPS_GOOD = '''\
"""Pure arithmetic operations."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ValueError("division by zero")
    return a / b
'''

# Buggy variant: no zero-guard -> the divide-by-zero test fails.
_CALC_OPS_BUGGY = '''\
"""Pure arithmetic operations."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    return a / b
'''

_CALC_INIT = '''\
"""calculator — a tiny arithmetic library."""

from .operations import add, subtract, multiply, divide

__all__ = ["add", "subtract", "multiply", "divide"]
'''

_CALC_TEST = '''\
import unittest

from calculator.operations import add, subtract, multiply, divide


class TestOperations(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_subtract(self):
        self.assertEqual(subtract(5, 3), 2)

    def test_multiply(self):
        self.assertEqual(multiply(4, 3), 12)

    def test_divide(self):
        self.assertEqual(divide(6, 3), 2)

    def test_divide_by_zero(self):
        with self.assertRaises(ValueError):
            divide(1, 0)


if __name__ == "__main__":
    unittest.main()
'''

_CALC_README = '''\
# calculator

A tiny arithmetic library: `add`, `subtract`, `multiply`, `divide`.
`divide` raises `ValueError` on division by zero.

```python
from calculator import add, divide
add(2, 3)      # 5
divide(6, 3)   # 2.0
```

Run tests: `python -m unittest discover -s tests -t .`
'''


def _calculator_plan(request: str) -> dict:
    return {
        "classification": {
            "domain": "python",
            "language": "python",
            "project_type": "library",
            "summary": "A Python arithmetic library with add/subtract/multiply/divide and tests.",
            "confidence": 0.95,
        },
        "design": {
            "root": "calculator_project",
            "files": [
                {"path": "calculator/__init__.py", "role": "boilerplate",
                 "purpose": "package exports", "spec": "re-export the four ops",
                 "depends_on": ["calculator/operations.py"]},
                {"path": "calculator/operations.py", "role": "core_logic",
                 "purpose": "arithmetic implementations",
                 "spec": "add/subtract/multiply/divide(a,b); divide raises ValueError on b==0",
                 "depends_on": []},
                {"path": "tests/test_operations.py", "role": "test",
                 "purpose": "unittest coverage of the four ops incl. zero-division",
                 "spec": "assert results and that divide(1,0) raises ValueError",
                 "depends_on": ["calculator/operations.py"]},
                {"path": "tests/__init__.py", "role": "boilerplate",
                 "purpose": "make tests an importable package for unittest discover",
                 "spec": "empty package init", "depends_on": []},
                {"path": "README.md", "role": "boilerplate",
                 "purpose": "usage docs", "spec": "short usage + test command",
                 "depends_on": []},
            ],
            "build": {
                "install": "",
                "test": "python -m unittest discover -s tests -t .",
                "entrypoint": "",
            },
            "notes": "Contract: divide(a, 0) raises ValueError('division by zero'). "
                     "Tests import `calculator.operations`.",
        },
        "files_good": {
            "calculator/__init__.py": _CALC_INIT,
            "calculator/operations.py": _CALC_OPS_GOOD,
            "tests/test_operations.py": _CALC_TEST,
            "README.md": _CALC_README,
        },
        "files_buggy": {
            "calculator/operations.py": _CALC_OPS_BUGGY,
        },
        "core_path": "calculator/operations.py",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Recipe: generic python module (fallback — always valid & green)
# ─────────────────────────────────────────────────────────────────────────────
def _module_plan(request: str) -> dict:
    name = _slug(request)
    mod = f"{name}.py"
    core = f'''\
"""{name} — generated from request: {request!r}"""


def run():
    """Entry point. Returns a short status string."""
    return "{name} ok"
'''
    test = f'''\
import unittest

from {name} import run


class Test{name.capitalize()}(unittest.TestCase):
    def test_run(self):
        self.assertEqual(run(), "{name} ok")


if __name__ == "__main__":
    unittest.main()
'''
    readme = f"# {name}\n\nGenerated module. Run tests: `python -m unittest discover -s tests -t .`\n"
    return {
        "classification": {
            "domain": "python", "language": "python", "project_type": "script",
            "summary": f"A minimal Python module for: {request}", "confidence": 0.6,
        },
        "design": {
            "root": f"{name}_project",
            "files": [
                {"path": mod, "role": "core_logic", "purpose": "module logic",
                 "spec": "run() -> str", "depends_on": []},
                {"path": "tests/test_main.py", "role": "test", "purpose": "smoke test",
                 "spec": "run() returns expected string", "depends_on": [mod]},
                {"path": "tests/__init__.py", "role": "boilerplate",
                 "purpose": "make tests an importable package", "spec": "empty",
                 "depends_on": []},
                {"path": "README.md", "role": "boilerplate", "purpose": "docs",
                 "spec": "usage", "depends_on": []},
            ],
            "build": {"install": "", "test": "python -m unittest discover -s tests -t .", "entrypoint": f"python -c 'import {name}; print({name}.run())'"},
            "notes": f"Single-module project; test imports `{name}`.",
        },
        "files_good": {mod: core, "tests/test_main.py": test, "README.md": readme},
        "files_buggy": {},
        "core_path": mod,
    }


def build_plan(request: str) -> dict:
    if choose_recipe(request) == "calculator":
        return _calculator_plan(request)
    return _module_plan(request)
