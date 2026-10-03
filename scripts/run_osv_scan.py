"""OSV 2.6.0: findings are advisory; malformed output and tool failures are not."""

import argparse
import json
import os
from pathlib import Path
import subprocess

from security_scan_results import osv_findings, osv_reporter_finding_count, read_json, require, validate_osv_sarif, validate_exit

# Same v2.6.0 image used by upstream action 7f58dd6750d78fc29a900ba64b1a0f946f62fba4.
IMAGE = "ghcr.io/google/osv-scanner-action:v2.6.0@sha256:71ad04ab2f8798be47870f9b18817ad317c2f8f2f97aa6726ba10d5578bc174a"
ROOT = Path(__file__).resolve().parents[1]
LOCK_ARGS = [
    "--lockfile=requirements.txt:./requirements.lock",
    "--lockfile=requirements.txt:./requirements-dev.lock",
    "--lockfile=./collector-desktop/package-lock.json",
    "--lockfile=./collector-desktop/src-tauri/Cargo.lock",
    "--lockfile=./game/web-app/package-lock.json",
]


def execute(command):
    # Scanner messages can contain source-controlled text. Never echo raw output.
    return subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=600, check=False).returncode


def probe_version(docker):
    result = subprocess.run(docker + ["--entrypoint", "/root/osv-scanner", IMAGE, "--version"],
                            capture_output=True, text=True, timeout=60, check=False)
    require(result.returncode == 0)
    # Probe the binary itself, never the image's exit_code_redirect.sh wrapper.
    require(any(line.lower().strip() == "osv-scanner version: 2.6.0"
                for line in (result.stdout + result.stderr).splitlines()))


def validate_bundle(output):
    identifiers = validate_osv_sarif(read_json(output / "results.json"), read_json(output / "results.sarif"))
    statuses = read_json(output / "status.json")
    validate_exit(statuses["scanner"], len(identifiers))
    validate_exit(statuses["reporter"], osv_reporter_finding_count(read_json(output / "results.json")))
    return identifiers


def scan(output):
    # Refuse stale output rather than accepting results from a previous run.
    output.mkdir(parents=True, exist_ok=False)
    require(execute(["docker", "pull", IMAGE]) == 0)
    docker = ["docker", "run", "--rm", "--workdir", "/github/workspace",
              "-v", f"{ROOT}:/github/workspace:ro", "-v", f"{output}:/reports",
              "-e", "GOTOOLCHAIN=auto"]
    probe_version(docker)
    status = execute(docker + ["--entrypoint", "/root/osv-scanner", IMAGE, "scan", "source",
        "--output-file=/reports/results.json", "--format=json", "--all-packages", "--all-vulns", *LOCK_ARGS])
    identifiers = osv_findings(read_json(output / "results.json"))
    validate_exit(status, len(identifiers))
    reporter = execute(docker + ["--entrypoint", "/root/osv-reporter", IMAGE,
        "--output=/reports/results.sarif\n--new=/reports/results.json\n"
        "--gh-annotations=false\n--fail-on-vuln=true\n--all-vulns"])
    validate_osv_sarif(read_json(output / "results.json"), read_json(output / "results.sarif"))
    validate_exit(reporter, osv_reporter_finding_count(read_json(output / "results.json")))
    (output / "status.json").write_text(json.dumps({"scanner": status, "reporter": reporter}),
                                        encoding="utf-8")
    return identifiers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("scan", "enforce"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        identifiers = scan(output) if args.mode == "scan" else validate_bundle(output)
        message = (f"OSV: valid scan, {len(identifiers)} distinct advisory IDs. "
                   "Full findings remain in SARIF and GitHub code scanning alerts.\n")
        if args.mode == "scan" and os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
                stream.write("### Development dependency report\n\n" + message)
                stream.write("\n".join(f"- `{identifier}`" for identifier in sorted(identifiers)))
                stream.write("\n\nSuccessful reporting is not release clearance.\n")
        print(message.strip())
        return 1 if args.mode == "enforce" and identifiers else 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError,
            subprocess.SubprocessError):
        print("::error::OSV execution or result validation failed; no clean result is claimed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
