import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from promptdelta.cli import main, read_json, write_json
from promptdelta.core import ConfigError
from promptdelta.providers import ChatProvider, ProviderError


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.mode = "ok"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append({"path": self.path, "key": self.headers.get("Authorization"), "body": body})
                if owner.mode == "timeout":
                    time.sleep(0.15)
                if owner.mode == "redirect":
                    self.send_response(307)
                    self.send_header("Location", "http://127.0.0.1:9/stolen")
                    self.end_headers()
                    return
                status = 401 if owner.mode == "error" else 200
                payload = {"choices": [{"finish_reason": "stop", "message": {"content": "7天内可以申请退货。"}}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18, "secret": "not exported"}}
                if owner.mode == "error":
                    payload = {"error": "echoed secret-key-value"}
                elif owner.mode == "bad":
                    payload = {"choices": [False]}
                elif owner.mode == "truncated":
                    payload["choices"][0]["finish_reason"] = "length"
                elif owner.mode == "large":
                    payload["padding"] = "x" * (2 * 1024 * 1024)
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port) + "/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_chat_request_and_usage_without_exporting_key(self):
        provider = ChatProvider(self.base, "test-model", "secret-key-value")
        result = provider.complete("case", "你好")
        self.assertEqual(result["text"], "7天内可以申请退货。")
        self.assertEqual(result["usage"], {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18})
        received = self.requests[0]
        self.assertEqual(received["path"], "/v1/chat/completions")
        self.assertEqual(received["key"], "Bearer secret-key-value")
        self.assertEqual(received["body"]["messages"], [{"role": "user", "content": "你好"}])
        self.assertFalse(received["body"]["stream"])
        self.assertNotIn("secret-key-value", json.dumps(provider.metadata()))

    def test_remote_http_and_embedded_credentials_are_rejected(self):
        for url in ("http://example.com/v1", "https://user:password@example.com/v1", "https://example.com/v1?key=x", "https://example.com:bad/v1"):
            with self.subTest(url=url), self.assertRaises(ConfigError):
                ChatProvider(url, "test")

    def test_api_errors_are_sanitized_and_redirects_not_followed(self):
        provider = ChatProvider(self.base, "test-model", "secret-key-value")
        for mode in ("error", "redirect", "bad", "truncated", "large"):
            self.mode = mode
            with self.subTest(mode=mode), self.assertRaises(ProviderError) as error:
                provider.complete("case", "input")
            self.assertNotIn("secret-key-value", str(error.exception))
            self.assertNotIn("not exported", str(error.exception))

    def test_timeout_is_an_execution_error(self):
        self.mode = "timeout"
        with self.assertRaisesRegex(ProviderError, "timed out"):
            ChatProvider(self.base, "test", timeout=0.03).complete("case", "input")

    def test_cli_live_flow_uses_env_key_and_errors_exit_two(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "suite.json", {"version": 1, "name": "mock", "cases": [
                {"id": "refund", "input": "退款", "assertions": [{"type": "contains", "value": "7天"}]}]})
            (root / "prompt.txt").write_text("用户：{{input}}", encoding="utf-8")
            args = ["run", "--provider", "api", "--base-url", self.base, "--model", "mock-model",
                    "--suite", str(root / "suite.json"), "--prompt", str(root / "prompt.txt"), "--out", str(root / "result.json")]
            with patch.dict("os.environ", {"PROMPTDELTA_API_KEY": "secret-key-value"}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
                self.mode = "error"
                self.assertEqual(main(args), 2)
            result = read_json(root / "result.json")
            self.assertEqual(result["summary"]["error"], 1)
            self.assertNotIn("secret-key-value", (root / "result.json").read_text(encoding="utf-8"))

    def test_invalid_timeouts_fail_before_request(self):
        for timeout in (0, -1, True, float("nan"), float("inf"), 1000):
            with self.subTest(timeout=timeout), self.assertRaises(ConfigError):
                ChatProvider(self.base, "mock", timeout=timeout)
