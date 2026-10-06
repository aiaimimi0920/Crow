"""Bounded passive Docker-log observation, independent of the interactive session.

Run on the Docker host with ``python -m tools.solver_observation``. This module
never invokes a solver, navigates a browser or writes authentication state.
"""

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.solver_observation_evidence import project_line, summarize

STATUS_PROBE = """
import json
from src.project_environment import getenv
from tools.internal_api_http import fetch_json
s=fetch_json(getenv('CROW_API_BASE_URL').rstrip('/')+'/status',timeout=15)
keys=('total_ids','captured_count','ai_finalized_count','seed_occurrence_total')
print(json.dumps({k:s.get(k) for k in keys if type(s.get(k)) is int}))
"""


def utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def docker(*args, timeout=30):
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def append(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def load_rows(path):
    return (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if path.exists()
        else []
    )


def inspect_container(name):
    obj = json.loads(docker("inspect", name).stdout)[0]
    if not obj["State"]["Running"]:
        raise RuntimeError("ContainerNotRunning")
    labels = obj["Config"].get("Labels") or {}
    return {
        "id": obj["Id"],
        "started_at": obj["State"]["StartedAt"],
        "image": obj["Image"],
        "project": labels.get("com.docker.compose.project"),
        "service": labels.get("com.docker.compose.service"),
    }


def write_report(root, run, events, samples, issues, cursor):
    report = summarize(events)
    start = samples[0]["counts"] if samples else {}
    end = samples[-1]["counts"] if samples else {}
    report.update(
        run=run,
        observed_through=utc(cursor),
        updated_at=utc(time.time()),
        window_finished=time.time() >= run["end_epoch"],
        logs_read_through_deadline=cursor >= run["end_epoch"],
        coverage_issues=issues,
        collection_delta={k: end[k] - v for k, v in start.items() if k in end},
        business_sample_count=len(samples),
        first_business_sample_at=samples[0]["at"] if samples else None,
        last_business_sample_at=samples[-1]["at"] if samples else None,
        limitations=[
            "Local success requires observed pyautogui drag, verified phase and success=true.",
            "Started counts emitted start events, not deduplicated business requests.",
            "Missing target/challenge linkage leaves auth confirmations unlinked.",
            "Auth proof requires correlated completion ID, automatic source and scope.",
            "Existing logs do not independently record every upstream /slide response.",
            "Business deltas are window-wide, not attributable to a specific solve.",
            "Concurrent human input cannot be excluded without independent input audit.",
            "Log rotation or events never emitted by the application may be undetectable.",
        ],
    )
    atomic_json(root / "report.json", report)


def observe(args):
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = root / "observer.lock"
    # flock is released on crashes/restarts; an existing file is not a live owner.
    import fcntl

    with lock.open("a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_path = root / "run.json"
        if run_path.exists():
            run = json.loads(run_path.read_text(encoding="utf-8"))
            if (
                run["container_name"] != args.container
                or run["source_revision"] != args.source_revision
            ):
                raise ValueError("ObservationIdentityMismatch")
        else:
            now = time.time()
            initial = inspect_container(args.container)
            run = {
                "start_epoch": now,
                "end_epoch": now + args.hours * 3600,
                "started_at": utc(now),
                "ends_at": utc(now + args.hours * 3600),
                "container_name": args.container,
                "initial_container": initial,
                "source_revision": args.source_revision,
                "passive_only": True,
                "interval_seconds": args.interval,
            }
            atomic_json(run_path, run)
        events = load_rows(root / "events.jsonl")
        samples = load_rows(root / "business.jsonl")
        issues = load_rows(root / "issues.jsonl")
        seen = {e["id"] for e in events}
        checkpoint = root / "checkpoint.json"
        cursor = (
            json.loads(checkpoint.read_text())["cursor"]
            if checkpoint.exists()
            else run["start_epoch"]
        )
        previous_id = (
            json.loads(checkpoint.read_text()).get("container_id")
            if checkpoint.exists()
            else run["initial_container"]["id"]
        )
        previous_started = (
            json.loads(checkpoint.read_text()).get("started_at")
            if checkpoint.exists()
            else run["initial_container"]["started_at"]
        )
        next_sample = 0
        while cursor < run["end_epoch"]:
            upper = min(time.time(), run["end_epoch"])
            container_id = previous_id
            current_started = previous_started
            read_ok = False
            try:
                current = inspect_container(args.container)
                container_id = current["id"]
                current_started = current["started_at"]
                expected = run["initial_container"]
                if any(current[k] != expected[k] for k in ("project", "service")):
                    raise RuntimeError("ContainerLabelsChanged")
                if container_id != previous_id:
                    issue = {
                        "at": utc(time.time()),
                        "kind": "container_changed",
                        "old": previous_id,
                        "new": container_id,
                    }
                    issues.append(issue)
                    append(root / "issues.jsonl", issue)
                projected = []
                ids = (
                    [previous_id, container_id]
                    if container_id != previous_id
                    else [container_id]
                )
                for cid in ids:
                    result = docker(
                        "logs",
                        "--timestamps",
                        "--since",
                        utc(max(run["start_epoch"], cursor - 2)),
                        "--until",
                        utc(upper),
                        cid,
                    )
                    for line in (result.stdout + "\n" + result.stderr).splitlines():
                        row = project_line(line, cid)
                        if (
                            row
                            and row["id"] not in seen
                            and run["start_epoch"] <= row["epoch"] <= run["end_epoch"]
                        ):
                            seen.add(row["id"])
                            projected.append(row)
                if current_started != previous_started:
                    from tools.solver_observation_evidence import fingerprint, timestamp

                    boundary = {
                        "kind": "observer_restart_boundary",
                        "at": current_started,
                        "epoch": timestamp(current_started),
                        "container_id": container_id,
                        "id": fingerprint(container_id + current_started),
                    }
                    if boundary["id"] not in seen:
                        seen.add(boundary["id"])
                        projected.append(boundary)
                read_ok = True
                for row in sorted(projected, key=lambda e: (e["epoch"], e["at"])):
                    append(root / "events.jsonl", row)
                    events.append(row)
                events.sort(key=lambda e: (e["epoch"], e["at"]))
                if time.time() >= next_sample or upper >= run["end_epoch"]:
                    next_sample = time.time() + 300
                    try:
                        data = json.loads(
                            docker(
                                "exec",
                                container_id,
                                "python",
                                "-B",
                                "-c",
                                STATUS_PROBE,
                                timeout=25,
                            ).stdout
                        )
                        sample = {"at": utc(time.time()), "counts": data}
                        samples.append(sample)
                        append(root / "business.jsonl", sample)
                    except Exception as error:  # noqa: BLE001 -- retain only safe error types
                        issue = {
                            "at": utc(time.time()),
                            "kind": "status_read_failed",
                            "error_type": type(error).__name__,
                        }
                        issues.append(issue)
                        append(root / "issues.jsonl", issue)
            except Exception as error:  # noqa: BLE001 -- retain only safe error types
                # Explicit gap, never report a failed log read as zero attempts.
                issue = {
                    "at": utc(time.time()),
                    "kind": "log_read_gap",
                    "from": utc(cursor),
                    "to": utc(upper),
                    "error_type": type(error).__name__,
                }
                issues.append(issue)
                append(root / "issues.jsonl", issue)
            if read_ok:
                cursor = upper
                previous_id = container_id
                previous_started = current_started
                atomic_json(
                    checkpoint,
                    {
                        "cursor": cursor,
                        "container_id": container_id,
                        "started_at": current_started,
                    },
                )
            write_report(root, run, events, samples, issues, cursor)
            if time.time() >= run["end_epoch"]:
                break
            if cursor < run["end_epoch"]:
                time.sleep(min(args.interval, max(0, run["end_epoch"] - time.time())))

        write_report(root, run, events, samples, issues, cursor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--interval", type=float, default=20)
    args = parser.parse_args()
    if not 0 < args.hours <= 48 or not 1 <= args.interval <= 300:
        parser.error("hours must be in (0,48], interval in [1,300]")
    os.umask(0o077)
    try:
        observe(args)
    except Exception as error:  # noqa: BLE001 -- retain only safe error types
        # Exception messages may contain raw subprocess output or credentials.
        print(json.dumps({"observer_error_type": type(error).__name__}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
