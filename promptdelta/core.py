"""Validated suites, deterministic assertions and conservative comparisons."""
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone


class ConfigError(ValueError):
    """Invalid configuration or incompatible result files."""


ASSERTIONS = {"equals", "contains", "not_contains", "regex", "json_valid", "json_path_equals", "max_length"}


def strict_json(text):
    def invalid(value):
        raise ValueError("Non-finite JSON number: " + value)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("JSON number is out of range")
        return result

    return json.loads(text, parse_constant=invalid, parse_float=finite_float, object_pairs_hook=unique)


def fingerprint(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_suite(suite):
    if not isinstance(suite, dict) or type(suite.get("version")) is not int or suite["version"] != 1:
        raise ConfigError("Suite must have version: 1")
    if not isinstance(suite.get("name"), str) or not suite["name"].strip():
        raise ConfigError("Suite needs a non-empty name")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ConfigError("Suite needs at least one case")
    ids = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ConfigError("Every case must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
            raise ConfigError("Case IDs must be unique, non-empty strings")
        ids.add(case_id)
        if not isinstance(case.get("input"), str):
            raise ConfigError(case_id + ": input must be a string")
        assertions = case.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            raise ConfigError(case_id + ": at least one assertion is required")
        for rule in assertions:
            validate_rule(rule, case_id)
    return suite


def validate_rule(rule, case_id="case"):
    if not isinstance(rule, dict) or not isinstance(rule.get("type"), str) or rule["type"] not in ASSERTIONS:
        raise ConfigError(case_id + ": unknown assertion type")
    kind = rule["type"]
    allowed = {"type"} if kind == "json_valid" else {"type", "value"}
    if kind == "json_path_equals":
        allowed.add("path")
    if set(rule) != allowed:
        raise ConfigError(case_id + ": assertion fields must be " + ", ".join(sorted(allowed)))
    if kind in {"equals", "contains", "not_contains", "regex"}:
        if not isinstance(rule["value"], str) or (kind != "equals" and not rule["value"]):
            raise ConfigError(case_id + ": assertion value must be a non-empty string")
    if kind == "regex":
        try:
            re.compile(rule["value"])
        except re.error as exc:
            raise ConfigError(case_id + ": invalid regular expression") from exc
    if kind == "max_length" and (type(rule["value"]) is not int or rule["value"] < 0):
        raise ConfigError(case_id + ": max_length needs a non-negative integer")
    if kind == "json_path_equals":
        path = rule["path"]
        if not isinstance(path, str) or (path and not path.startswith("/")) or re.search(r"~(?![01])", path):
            raise ConfigError(case_id + ": path must be a JSON Pointer, e.g. /order/id")


def json_equal(left, right):
    # Python considers True == 1; structured output assertions must not.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def json_pointer(value, path):
    if not path:
        return value
    for raw in path[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            value = value[int(token)]
        else:
            raise KeyError(path)
    return value


def evaluate(output, rule):
    kind = rule["type"]
    value = rule.get("value")
    detail = ""
    if kind == "equals":
        passed = output == value
    elif kind == "contains":
        passed = value in output
    elif kind == "not_contains":
        passed = value not in output
    elif kind == "regex":
        passed = re.search(value, output) is not None
    elif kind == "max_length":
        passed = len(output) <= value
        detail = "{} characters (limit {})".format(len(output), value)
    else:
        try:
            parsed = strict_json(output)
            if kind == "json_valid":
                passed = True
            else:
                passed = json_equal(json_pointer(parsed, rule["path"]), value)
        except (ValueError, KeyError, IndexError, RecursionError):
            passed = False
            detail = "Invalid JSON or missing JSON Pointer"
    return {"rule": rule, "passed": passed, "detail": detail}


def suite_identity(suite):
    # Ordering does not affect compatibility. Inputs AND assertions do.
    return fingerprint(sorted(suite["cases"], key=lambda c: c["id"]))


def run_suite(suite, prompt, provider, label):
    validate_suite(suite)
    if not isinstance(prompt, str) or "{{input}}" not in prompt:
        raise ConfigError("Prompt must contain {{input}}")
    results = []
    for case in suite["cases"]:
        rendered = prompt.replace("{{input}}", case["input"])
        started = time.perf_counter()
        try:
            response = provider.complete(case["id"], rendered)
            output = response["text"]
            if not isinstance(output, str):
                raise ValueError("Provider output is not text")
        except Exception as exc:
            # Providers only expose sanitized errors; unexpected programmer errors
            # are deliberately not copied into reports where secrets could leak.
            from .providers import ProviderError
            if not isinstance(exc, ProviderError):
                raise
            results.append({"id": case["id"], "input": case["input"], "status": "error", "output": "",
                            "error": str(exc), "checks": [], "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                            "usage": None})
            continue
        checks = [evaluate(output, rule) for rule in case["assertions"]]
        results.append({"id": case["id"], "input": case["input"], "status": "pass" if all(c["passed"] for c in checks) else "fail",
                        "output": output, "error": None, "checks": checks,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2), "usage": response.get("usage")})
    counts = {status: sum(r["status"] == status for r in results) for status in ("pass", "fail", "error")}
    return {"version": 1, "kind": "run", "label": label, "suite_name": suite["name"],
            "suite_hash": suite_identity(suite), "prompt_hash": fingerprint(prompt),
            "provider": provider.metadata(), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": {**counts, "total": len(results), "pass_rate": counts["pass"] / len(results)}, "cases": results}


def validate_run(run):
    if not isinstance(run, dict) or run.get("kind") != "run" or type(run.get("version")) is not int or run["version"] != 1:
        raise ConfigError("Unsupported run result")
    for key in ("label", "suite_name", "suite_hash", "prompt_hash"):
        if not isinstance(run.get(key), str) or not run[key]:
            raise ConfigError("Invalid run field: " + key)
    provider = run.get("provider")
    if not isinstance(provider, dict) or provider.get("type") not in ("api", "recorded") or not isinstance(provider.get("model"), str):
        raise ConfigError("Invalid provider metadata in run")
    cases = run.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ConfigError("Run must contain cases")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"] or case["id"] in ids:
            raise ConfigError("Invalid or duplicate case ID in run")
        ids.add(case["id"])
        if case.get("status") not in ("pass", "fail", "error") or not isinstance(case.get("output"), str) or not isinstance(case.get("input"), str):
            raise ConfigError("Invalid case result")
        if not isinstance(case.get("checks"), list):
            raise ConfigError("Invalid assertion results")
        if case["status"] == "error" and (not isinstance(case.get("error"), str) or not case["error"]):
            raise ConfigError("Execution error needs an error message")
        for check in case["checks"]:
            if not isinstance(check, dict) or type(check.get("passed")) is not bool:
                raise ConfigError("Invalid assertion result")
            validate_rule(check.get("rule"))
        if case["status"] != "error":
            checks = case["checks"]
            expected = "pass" if checks and all(c["passed"] for c in checks) else "fail"
            if case["status"] != expected or not checks:
                raise ConfigError("Case status disagrees with its assertion results")
    return run


def compare_runs(baseline, candidate):
    validate_run(baseline)
    validate_run(candidate)
    if baseline["suite_hash"] != candidate["suite_hash"]:
        raise ConfigError("Suites differ: keep case IDs, inputs and assertions unchanged when comparing prompts")
    old = {case["id"]: case for case in baseline["cases"]}
    new = {case["id"]: case for case in candidate["cases"]}
    if old.keys() != new.keys():
        raise ConfigError("Case IDs differ between runs")
    changes = []
    for case_id, before in old.items():
        after = new[case_id]
        if before["input"] != after["input"] or [c["rule"] for c in before["checks"]] != [c["rule"] for c in after["checks"]]:
            # Error cases have no checks; compatibility is already bound by suite_hash.
            if before["input"] != after["input"] or (before["status"] != "error" and after["status"] != "error"):
                raise ConfigError("Case content differs: " + case_id)
        if "error" in (before["status"], after["status"]):
            change = "error"
        elif before["status"] == "pass" and after["status"] == "fail":
            change = "regression"
        elif before["status"] == "fail" and after["status"] == "pass":
            change = "improvement"
        else:
            change = "unchanged"
        changes.append({"id": case_id, "change": change, "before": before, "after": after})
    summary = {kind: sum(c["change"] == kind for c in changes) for kind in ("regression", "improvement", "unchanged", "error")}
    summary["baseline_pass"] = sum(c["status"] == "pass" for c in baseline["cases"])
    summary["candidate_pass"] = sum(c["status"] == "pass" for c in candidate["cases"])
    summary["total"] = len(changes)
    return {"version": 1, "kind": "comparison", "suite_name": baseline["suite_name"],
            "baseline_label": baseline["label"], "candidate_label": candidate["label"],
            "baseline_provider": baseline["provider"], "candidate_provider": candidate["provider"],
            "baseline_prompt_hash": baseline["prompt_hash"], "candidate_prompt_hash": candidate["prompt_hash"],
            "summary": summary, "cases": changes}
