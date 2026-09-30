"""Run quality gates from isolated storage, never an installed application's data."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from quality_suites import SUITES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES, default="fast")
    parser.add_argument("--timing-report", type=Path, help="Optional phase timing JSON")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = tempfile.mkdtemp(prefix="crow-quality-")
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "FAPAI_DB_ENABLED": "0",
            "FAPAI_DB_URL": "",
            "FAPAI_DB_AUTO_CREATE": "0",
            "FAPAI_SOLVER_STATE_DIR": runtime,
            "FAPAI_DATA_ROOT": runtime,
            "FAPAI_DATA_ROOT_HOST": runtime,
            "CROW_DATA_ROOT_HOST": runtime,
            "FAPAI_NAS_AUTH_RECOVERY_ENABLED": "0",
            "FAPAI_SOLVER_OS_MOUSE": "0",
            "FAPAI_COLLECTION_WORKER_TOKEN_FILE": "",
            "FAPAI_API_CA_FILE": "",
            "FAPAI_ENGINE_OPERATOR_TOKEN_FILE": "",
            "FAPAI_ENGINE_AGENT_TOKEN_FILE": "",
            "FAPAI_CONTROL_PLANE_TOKEN": "",
            "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE": "",
            "FAPAI_ANALYSIS_MODEL_POOL_PATH": str(Path(runtime) / "model-pool.sqlite3"),
        }
    )
    if args.suite != "postgres":
        env["CROW_TEST_POSTGRES_URL"] = ""
    elif not env.get("CROW_TEST_POSTGRES_URL"):
        parser.error("The postgres gate requires a dedicated CROW_TEST_POSTGRES_URL")
    # One directory argument avoids repeated pytest directory collection per file.
    # The plugin rejects unselected paths before their collectors are constructed.
    env["CROW_QUALITY_SELECTION"] = json.dumps(
        ["tools/test/" + name.replace("\\", "/") for name in SUITES[args.suite]]
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--rootdir",
        str(root),
        "-q",
        "--tb=short",
        "--durations=5",
        "-p",
        "no:cacheprovider",
        "-p",
        "scripts.quality_selection",
        "-o",
        "python_files="
        + " ".join(
            dict.fromkeys(
                Path(name.split("::", 1)[0]).name for name in SUITES[args.suite]
            )
        ),
        str(root / "tools" / "test"),
    ]
    env.pop("CROW_QUALITY_TIMING_REPORT", None)
    if args.timing_report:
        report = args.timing_report.resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        env["CROW_QUALITY_TIMING_REPORT"] = str(report)
        command.extend(["-p", "scripts.quality_timing"])
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=runtime, env=env, check=False, timeout=180)
    except subprocess.TimeoutExpired:
        print("Quality gate exceeded its 180 second execution limit", file=sys.stderr)
        return 1
    elapsed = time.monotonic() - started
    print(
        f"Quality suite={args.suite} elapsed={elapsed:.2f}s isolated_storage={runtime}"
    )
    if args.suite == "fast" and elapsed >= 60:
        print("Fast quality gate exceeded 60 seconds", file=sys.stderr)
        return 1
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
