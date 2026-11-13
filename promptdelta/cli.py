"""Small CLI; exit codes are suitable for a CI quality gate."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .core import ConfigError, compare_runs, run_suite, strict_json, validate_suite
from .providers import ChatProvider, RecordedProvider
from .report import render_comparison


def read_json(path):
    try:
        return strict_json(Path(path).read_text(encoding="utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        raise ConfigError("Invalid JSON file: " + str(path)) from exc


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(str(temporary), str(path))
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def distinct_outputs(outputs, inputs):
    resolved = [Path(p).resolve() for p in outputs if p]
    sources = {Path(p).resolve() for p in inputs if p}
    if len(set(resolved)) != len(resolved) or any(path in sources for path in resolved):
        raise ConfigError("Output paths must be distinct and must not overwrite input files")


def demo(output):
    from .demo_data import BASELINE, CANDIDATE, PROMPT_V1, PROMPT_V2, SUITE
    output = Path(output)
    baseline = run_suite(SUITE, PROMPT_V1, RecordedProvider(BASELINE), "baseline-v1")
    candidate = run_suite(SUITE, PROMPT_V2, RecordedProvider(CANDIDATE), "candidate-v2")
    comparison = compare_runs(baseline, candidate)
    for name, value in (("baseline", baseline), ("candidate", candidate), ("comparison", comparison)):
        write_json(output / (name + ".json"), value)
    write_text(output / "report.html", render_comparison(comparison))
    print("Offline demo: 6 cases, 2 regressions, 1 improvement (recorded fixtures, no model calls).")
    print("Report: " + str((output / "report.html").resolve()))
    return 0


def parser():
    root = argparse.ArgumentParser(description="PromptDelta: test prompts and catch output regressions")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("demo", help="Create a complete offline demo without API keys")
    sample.add_argument("--out", default="reports/demo", help="Output directory")
    validate = commands.add_parser("validate", help="Validate a suite before making API calls")
    validate.add_argument("suite")
    run = commands.add_parser("run", help="Run one prompt against a fixed suite")
    run.add_argument("--suite", required=True)
    run.add_argument("--prompt", required=True)
    run.add_argument("--provider", choices=("recorded", "api"), default="recorded")
    run.add_argument("--responses", help="JSON mapping of case IDs to recorded text")
    run.add_argument("--base-url", help="Chat Completions API base URL, e.g. https://api.openai.com/v1")
    run.add_argument("--model")
    run.add_argument("--timeout", type=float, default=30)
    run.add_argument("--label", default="run")
    run.add_argument("--out", required=True, help="JSON result file")
    compare = commands.add_parser("compare", help="Compare compatible runs; fail CI on regressions")
    compare.add_argument("baseline")
    compare.add_argument("candidate")
    compare.add_argument("--out", default="reports/comparison.json")
    compare.add_argument("--html", default="reports/comparison.html")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            return demo(args.out)
        if args.command == "validate":
            suite = validate_suite(read_json(args.suite))
            print("Valid suite: {} ({} cases)".format(suite["name"], len(suite["cases"])))
            return 0
        if args.command == "run":
            distinct_outputs([args.out], [args.suite, args.prompt, args.responses])
            suite = validate_suite(read_json(args.suite))
            prompt = Path(args.prompt).read_text(encoding="utf-8-sig")
            if args.provider == "recorded":
                if not args.responses or args.base_url or args.model:
                    raise ConfigError("Recorded mode needs --responses and does not accept --base-url or --model")
                provider = RecordedProvider(read_json(args.responses))
                expected = {case["id"] for case in suite["cases"]}
                if provider.responses.keys() != expected:
                    raise ConfigError("Recorded response IDs must exactly match the suite")
            else:
                if args.responses or not args.base_url or not args.model:
                    raise ConfigError("API mode needs --base-url and --model; do not supply --responses")
                provider = ChatProvider(args.base_url, args.model, os.environ.get("PROMPTDELTA_API_KEY", ""), args.timeout)
            result = run_suite(suite, prompt, provider, args.label)
            write_json(args.out, result)
            s = result["summary"]
            print("{}: {} passed, {} failed, {} errors / {}".format(args.label, s["pass"], s["fail"], s["error"], s["total"]))
            return 2 if s["error"] else (1 if s["fail"] else 0)
        distinct_outputs([args.out, args.html], [args.baseline, args.candidate])
        comparison = compare_runs(read_json(args.baseline), read_json(args.candidate))
        write_json(args.out, comparison)
        write_text(args.html, render_comparison(comparison))
        s = comparison["summary"]
        print("{} regressions, {} improvements, {} unchanged, {} errors".format(s["regression"], s["improvement"], s["unchanged"], s["error"]))
        print("Report: " + str(Path(args.html).resolve()))
        return 2 if s["error"] else (1 if s["regression"] else 0)
    except (ConfigError, OSError, UnicodeError, RecursionError) as exc:
        message = str(exc) if isinstance(exc, ConfigError) else "Could not read or write files; check paths and permissions"
        print("Error: " + message, file=sys.stderr)
        return 2
