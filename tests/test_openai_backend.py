"""Validate the OpenAI-compatible (llama.cpp) backend WITHOUT a GPU.

Stands up a stdlib HTTP server that speaks the OpenAI ``/chat/completions``
protocol and answers each orchestrator mode using the same deterministic logic as
the mock backend. Running the full pipeline against it over a real socket proves
the transport, JSON round-trip, response parsing, and sequential-swap wiring all
work — i.e. it would run against real llama.cpp servers on the 4090.
"""

import json
import os
import re
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from clid.config import get_settings
from clid.llm.client import MockLLM

REQUEST = "Build a Python calculator library with tests"
_MOCK = MockLLM("server")


def _detect_mode(system: str) -> str:
    for mode in ("classify", "design", "delegate", "diagnose", "judge"):
        if f"`{mode}` mode" in system:
            return mode
    return "coder"  # coder.md has no "`<mode>` mode" marker


def _answer(system: str, user: str) -> dict:
    mode = _detect_mode(system)
    ctx: dict = {"request": REQUEST}
    if mode == "coder":
        m = re.search(r"Build the file:\s*(\S+)", user)
        ctx["path"] = m.group(1) if m else ""
        ctx["attempt"] = 0
    elif mode == "judge":
        ctx.update(tool_output=user, focus_path="", retries={}, thresholds={})
    return _MOCK.chat(mode=mode, system=system, user=user, context=ctx)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):  # silence
        pass

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body["messages"]
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        content = json.dumps(_answer(system, user))
        payload = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]})
        data = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class TestOpenAIBackend(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        base = f"http://127.0.0.1:{self.port}/v1"
        os.environ["CLID_BACKEND"] = "openai"
        os.environ["CLID_ORCH_BASE_URL"] = base
        os.environ["CLID_CODER_BASE_URL"] = base
        get_settings.cache_clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for k in ("CLID_BACKEND", "CLID_ORCH_BASE_URL", "CLID_CODER_BASE_URL"):
            os.environ.pop(k, None)
        get_settings.cache_clear()

    def test_pipeline_runs_over_http(self):
        from clid.graph.pipeline import Pipeline

        settings = get_settings()
        self.assertEqual(settings.backend, "openai")
        with tempfile.TemporaryDirectory() as tmp:
            settings.workspaces_dir = Path(tmp) / "ws"
            settings.runs_dir = Path(tmp) / "runs"
            final = Pipeline(settings, "http-run").run(REQUEST)
        self.assertEqual(final["status"], "done", final.get("result"))
        self.assertTrue(final["result"]["tests_passed"])
        self.assertIn("calculator/operations.py", final["result"]["files"])
        # sequential-swap still recorded when talking to real HTTP endpoints
        self.assertGreaterEqual(final["result"]["swaps"], 3)


if __name__ == "__main__":
    unittest.main()
