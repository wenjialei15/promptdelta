import copy
import unittest

from promptdelta.core import ConfigError, compare_runs, evaluate, run_suite, strict_json, validate_suite
from promptdelta.demo_data import BASELINE, CANDIDATE, PROMPT_V1, PROMPT_V2, SUITE
from promptdelta.providers import ProviderError, RecordedProvider
from promptdelta.report import render_comparison


class CoreTests(unittest.TestCase):
    def run_fixture(self, responses=BASELINE):
        return run_suite(copy.deepcopy(SUITE), PROMPT_V1, RecordedProvider(responses), "fixture")

    def test_demo_classifies_regressions_and_improvement(self):
        old = self.run_fixture()
        new = run_suite(SUITE, PROMPT_V2, RecordedProvider(CANDIDATE), "candidate")
        comparison = compare_runs(old, new)
        s = comparison["summary"]
        self.assertEqual((s["regression"], s["improvement"], s["unchanged"], s["error"]), (2, 1, 3, 0))
        self.assertEqual((s["baseline_pass"], s["candidate_pass"]), (5, 4))
        self.assertNotEqual(old["prompt_hash"], new["prompt_hash"])
        self.assertEqual(old["suite_hash"], new["suite_hash"])

    def test_changed_dataset_or_assertions_cannot_be_compared(self):
        old = self.run_fixture()
        for mutate in (lambda s: s["cases"][0].update(input="changed"),
                       lambda s: s["cases"][0]["assertions"][0].update(value="changed"),
                       lambda s: s["cases"].pop()):
            suite = copy.deepcopy(SUITE)
            mutate(suite)
            new = run_suite(suite, PROMPT_V1, RecordedProvider(BASELINE), "new")
            with self.assertRaises(ConfigError):
                compare_runs(old, new)

    def test_case_order_does_not_change_identity_or_alignment(self):
        suite = copy.deepcopy(SUITE)
        suite["cases"].reverse()
        new = run_suite(suite, PROMPT_V1, RecordedProvider(BASELINE), "reordered")
        comparison = compare_runs(self.run_fixture(), new)
        self.assertEqual(comparison["summary"]["unchanged"], 6)

    def test_assertions_cover_text_json_and_length(self):
        examples = [
            ("你好", {"type": "equals", "value": "你好"}, True),
            ("hello", {"type": "contains", "value": "ell"}, True),
            ("hello", {"type": "not_contains", "value": "ell"}, False),
            ("A1024", {"type": "regex", "value": "^A[0-9]+$"}, True),
            ("你好", {"type": "max_length", "value": 2}, True),
            ("你好！", {"type": "max_length", "value": 2}, False),
            ('{"ok":true}', {"type": "json_valid"}, True),
            ('```json\n{}\n```', {"type": "json_valid"}, False),
        ]
        for output, rule, passed in examples:
            with self.subTest(rule=rule):
                self.assertEqual(evaluate(output, rule)["passed"], passed)

    def test_json_pointer_handles_lists_escapes_null_and_missing(self):
        output = '{"a/b":{"~key":[null,2]}}'
        for pointer, value, passed in (("/a~1b/~0key/0", None, True), ("/a~1b/~0key/1", 2, True),
                                       ("/missing", None, False), ("/a~1b/~0key/-1", 2, False),
                                       ("/a~1b/~0key/01", 2, False), ("/a~1b/~0key/9", None, False)):
            with self.subTest(pointer=pointer):
                self.assertEqual(evaluate(output, {"type": "json_path_equals", "path": pointer, "value": value})["passed"], passed)

    def test_json_comparisons_are_type_sensitive_including_nested_values(self):
        for output, expected in (("true", 1), ("2", "2"), ("2.0", 2), ('{"x":[true]}', {"x": [1]})):
            self.assertFalse(evaluate(output, {"type": "json_path_equals", "path": "", "value": expected})["passed"])

    def test_invalid_and_ambiguous_json_is_rejected(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_json(text)

    def test_invalid_suites_fail_before_execution(self):
        bad = [None, {}, {"version": True, "name": "x", "cases": []}]
        for mutation in (lambda s: s["cases"].append(s["cases"][0]),
                         lambda s: s["cases"][0].update(assertions=[]),
                         lambda s: s["cases"][0].update(input=3),
                         lambda s: s["cases"][0].update(assertions=[{"type": "contains", "vlaue": "x"}]),
                         lambda s: s["cases"][0].update(assertions=[{"type": []}]),
                         lambda s: s["cases"][0].update(assertions=[{"type": "regex", "value": "["}]),
                         lambda s: s["cases"][0].update(assertions=[{"type": "json_path_equals", "path": "/a~2b", "value": 1}])):
            suite = copy.deepcopy(SUITE)
            mutation(suite)
            bad.append(suite)
        for suite in bad:
            with self.subTest(suite=str(suite)[:50]), self.assertRaises(ConfigError):
                validate_suite(suite)

    def test_provider_errors_are_not_reported_as_improvements(self):
        class Broken:
            def complete(self, case_id, prompt):
                raise ProviderError("API HTTP 401")

            def metadata(self):
                return {"type": "api", "model": "mock"}

        broken = run_suite(SUITE, PROMPT_V1, Broken(), "broken")
        for before, after in ((self.run_fixture(), broken), (broken, self.run_fixture())):
            comparison = compare_runs(before, after)
            self.assertEqual(comparison["summary"]["error"], 6)
            self.assertEqual(comparison["summary"]["improvement"], 0)

    def test_unexpected_programming_errors_are_not_silently_swallowed(self):
        class Broken(RecordedProvider):
            def complete(self, case_id, prompt):
                raise RuntimeError("programmer error")

        with self.assertRaises(RuntimeError):
            run_suite(SUITE, PROMPT_V1, Broken(BASELINE), "broken")

    def test_prompt_placeholder_is_required_and_inserted_literally(self):
        with self.assertRaises(ConfigError):
            run_suite(SUITE, "no placeholder", RecordedProvider(BASELINE), "bad")
        class Capture(RecordedProvider):
            def complete(inner, case_id, prompt):
                self.assertIn("{\"example\": 2}", prompt)
                self.assertNotIn("{{input}}", prompt)
                return super().complete(case_id, prompt)
        run_suite(SUITE, '{"example": 2}\n{{input}}', Capture(BASELINE), "capture")

    def test_malformed_run_files_are_rejected(self):
        old = self.run_fixture()
        for mutate in (lambda r: r["cases"].append(r["cases"][0]),
                       lambda r: r.pop("provider"),
                       lambda r: r["cases"][0].update(status="unknown"),
                       lambda r: r["cases"][0].update(status="pass", checks=[]),
                       lambda r: r["cases"][0].update(input="tampered")):
            new = copy.deepcopy(old)
            mutate(new)
            with self.assertRaises(ConfigError):
                compare_runs(old, new)

    def test_report_escapes_untrusted_output_and_labels(self):
        old = self.run_fixture()
        new = self.run_fixture()
        new["label"] = '<img src=x onerror="alert(1)">'
        new["cases"][0]["output"] = '</pre><script>alert(1)</script>'
        report = render_comparison(compare_runs(old, new))
        self.assertNotIn('<script>alert(1)</script>', report)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', report)
        self.assertNotIn('<img src=x', report)
        self.assertIn("离线回放", report)


if __name__ == "__main__":
    unittest.main()
