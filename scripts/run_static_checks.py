"""Run every configured static check independently from functional jobs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from security_scan_results import read_json, require
from static_result_parsers import classify, effective_findings

ROOT = Path(__file__).resolve().parents[1]


def commands(group):
    if group == "python":
        for command in read_json(ROOT / "scripts/static-checks.json"):
            require(command[:2] == ["python", "-m"] and command[2] in {"ruff", "mypy"})
            extra = ["--output-format=json"] if command[2] == "ruff" else ["--output=json"]
            yield command[2], [sys.executable, *command[1:], *extra], ROOT
    elif group == "effective":
        yield "effective", ["node", "scripts/effective-code-lines.mjs", "--mode", "ratchet",
                            "--json", ".security-results/effective-raw.json"], ROOT
    else:
        desktop = ROOT / "collector-desktop"
        yield "oxlint", ["node", "node_modules/oxlint/bin/oxlint", "--deny-warnings", "src", "tests",
                          "playwright.config.ts", "--format=json"], desktop
        yield "rustfmt", ["cargo", "+1.90.0", "fmt", "--check", "--manifest-path", "src-tauri/Cargo.toml"], desktop


def report(group, target):
    require(not target.exists())
    if group == "effective":
        require(not (ROOT / ".security-results/effective-raw.json").exists())
    reports = []
    for index, (kind, command, cwd) in enumerate(commands(group)):
        entry = {"index": index, "tool": kind, "complete": False, "findings": []}
        try:
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                    encoding="utf-8", timeout=180, check=False)
            if kind == "effective":
                rows = effective_findings(read_json(ROOT / ".security-results/effective-raw.json"),
                                          result.returncode, ROOT)
            else:
                rows = classify(kind, result.returncode, result.stdout, result.stderr, cwd)
            entry.update(complete=True, findings=rows)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
            entry["error"] = "tool_or_result_failure"
        reports.append(entry)
    require(bool(reports))
    target.parent.mkdir(parents=True, exist_ok=True)
    require(not target.exists())
    target.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    failed = sum(not item["complete"] for item in reports)
    count = sum(len(item["findings"]) for item in reports)
    message = f"Static {group}: {len(reports)} checks, {count} findings, {failed} tool/report failures.\n"
    print(message.strip())
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write("### Static quality report\n\n" + message)
            stream.write("All finding locations and rule codes are retained in the report artifact.\n")
    return 2 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("python", "desktop", "effective", "enforce"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.mode != "enforce":
            return report(args.mode, args.output)
        results = read_json(args.output)
        require(isinstance(results, list) and bool(results))
        require(all(isinstance(r, dict) and r.get("complete") is True and
                    isinstance(r.get("findings"), list) for r in results))
        return 1 if any(r["findings"] for r in results) else 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print("::error::Static quality report could not be validated.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
