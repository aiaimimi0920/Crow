"""Run a scheduled Windows child without allocating a console; retain its exit code."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def write_status(path: Path, status: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(status), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-path", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if os.name != "nt" or not command:
        return 2
    status = {"started_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid()}
    try:
        write_status(args.status_path, {**status, "phase": "starting"})
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        # Wait in the scheduler-owned process: IgnoreNew and the task timeout still apply.
        with subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
            startupinfo=startup,
        ) as child:
            status["child_pid"] = child.pid
            write_status(args.status_path, {**status, "phase": "running"})
            result = child.wait()
        status.update(phase="finished", exit_code=result)
    except OSError as exc:
        result = 1
        status.update(
            phase="launch_failed", exit_code=result, error_type=type(exc).__name__
        )
    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    try:
        write_status(args.status_path, status)
    except OSError:
        return result or 1
    return result


if __name__ == "__main__":
    sys.exit(main())
