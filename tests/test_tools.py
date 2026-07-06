"""Deterministic tools: workspace safety, manifest, templater, runners."""

import tempfile
import unittest
from pathlib import Path

from clid.schemas import Design, FilePlan
from clid.tools import Workspace, WorkspaceError, compile_python
from clid.tools.manifest import file_signatures
from clid.tools.sandbox import LocalSandbox
from clid.tools.runners import run_tests
from clid.tools.templater import render_template


class TestWorkspace(unittest.TestCase):
    def test_write_read_and_traversal_guard(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            ws.write("pkg/mod.py", "x = 1\n")
            self.assertEqual(ws.read("pkg/mod.py"), "x = 1\n")
            self.assertIn("pkg/mod.py", ws.list_files())
            with self.assertRaises(WorkspaceError):
                ws.write("../escape.py", "nope")


class TestManifest(unittest.TestCase):
    def test_top_level_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.py"
            p.write_text(
                "def top(a, b):\n    return a\n\nclass C:\n    def method(self):\n        return 1\n",
                encoding="utf-8",
            )
            sigs = file_signatures(p)
            self.assertIn("def top(a, b)", sigs)
            self.assertIn("class C", sigs)
            self.assertFalse(any("method" in s for s in sigs))  # indented → excluded


class TestTemplater(unittest.TestCase):
    def test_init_reexports_siblings(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            ws.write("calc/operations.py", "def add(a, b):\n    return a + b\n\ndef _hidden():\n    pass\n")
            design = Design(root="p", files=[FilePlan(path="calc/__init__.py", role="boilerplate")])
            content = render_template("calc/__init__.py", design, ws)
            self.assertIn("from .operations import add", content)
            self.assertNotIn("_hidden", content)  # private excluded
            self.assertIn('__all__ = ["add"]', content)


class TestRunners(unittest.TestCase):
    def test_compile_detects_syntax_error(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            ws.write("good.py", "x = 1\n")
            ok, _ = compile_python(ws.root)
            self.assertTrue(ok)
            ws.write("bad.py", "def broken(:\n")
            ok, out = compile_python(ws.root)
            self.assertFalse(ok)

    def test_run_tests_pass(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(d)
            ws.write("tests/__init__.py", "")
            ws.write("tests/test_ok.py",
                     "import unittest\n\nclass T(unittest.TestCase):\n"
                     "    def test_ok(self):\n        self.assertEqual(1 + 1, 2)\n")
            passed, _out = run_tests(LocalSandbox(), ws.root, "python -m unittest discover -s tests -t .")
            self.assertTrue(passed)


if __name__ == "__main__":
    unittest.main()
