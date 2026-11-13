import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from promptdelta.cli import main, read_json, write_json
from promptdelta.demo_data import BASELINE, CANDIDATE, PROMPT_V1, SUITE


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.suite = self.root / "suite.json"
        self.prompt = self.root / "prompt.txt"
        self.responses = self.root / "responses.json"
        write_json(self.suite, SUITE)
        self.prompt.write_text(PROMPT_V1, encoding="utf-8")
        write_json(self.responses, BASELINE)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main([str(arg) for arg in args])

    def run_args(self, out):
        return ["run", "--suite", self.suite, "--prompt", self.prompt, "--responses", self.responses, "--out", out]

    def test_demo_runs_without_secrets_or_network(self):
        output = self.root / "demo"
        with patch.dict("os.environ", {}, clear=True), patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network")):
            self.assertEqual(self.call(["demo", "--out", output]), 0)
        self.assertEqual(read_json(output / "comparison.json")["summary"]["regression"], 2)
        self.assertTrue((output / "report.html").read_text(encoding="utf-8").startswith("<!doctype html>"))

    def test_validate_and_run_exit_codes(self):
        self.assertEqual(self.call(["validate", self.suite]), 0)
        self.assertEqual(self.call(self.run_args(self.root / "baseline.json")), 1)
        good = copy.deepcopy(SUITE)
        good["cases"] = [good["cases"][0]]
        write_json(self.suite, good)
        write_json(self.responses, {"refund-policy": BASELINE["refund-policy"]})
        self.assertEqual(self.call(self.run_args(self.root / "pass.json")), 0)

    def test_compare_fails_for_regression_and_passes_for_same_run(self):
        output = self.root / "demo"
        self.call(["demo", "--out", output])
        args = ["compare", output / "baseline.json", output / "candidate.json", "--out", self.root / "diff.json", "--html", self.root / "diff.html"]
        self.assertEqual(self.call(args), 1)
        args[2] = output / "baseline.json"
        self.assertEqual(self.call(args), 0)

    def test_input_files_cannot_be_overwritten_by_outputs(self):
        original = self.suite.read_bytes()
        self.assertEqual(self.call(self.run_args(self.suite)), 2)
        self.assertEqual(self.suite.read_bytes(), original)

    def test_missing_extra_and_misspelled_response_ids_are_errors(self):
        for responses in ({}, {**BASELINE, "typo": "response"}):
            write_json(self.responses, responses)
            output = self.root / "bad.json"
            self.assertEqual(self.call(self.run_args(output)), 2)
            self.assertFalse(output.exists())

    def test_bad_config_and_files_return_two_without_traceback(self):
        self.assertEqual(self.call(["validate", self.root / "missing.json"]), 2)
        self.suite.write_text('{"version":1,"version":2}', encoding="utf-8")
        self.assertEqual(self.call(["validate", self.suite]), 2)
        self.assertEqual(self.call(["run", "--suite", self.suite, "--prompt", self.prompt, "--out", self.root / "x.json", "--provider", "api"]), 2)

    def test_outputs_with_unicode_paths(self):
        output = self.root / "中文目录" / "测试报告"
        self.assertEqual(self.call(["demo", "--out", output]), 0)
        self.assertEqual(read_json(output / "comparison.json")["summary"]["total"], 6)
