"""Hard deadline for detail Playwright capture, including driver/cleanup waits."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_CAPTURE_SECONDS = 180.0
CLEANUP_SECONDS = 5.0
REPO_ROOT = Path(__file__).resolve().parents[1]


def run_capture_process(
    command, request, *, timeout_seconds=DEFAULT_CAPTURE_SECONDS, cwd=REPO_ROOT
):
    """Drain large replies while waiting; terminate only our helper and descendants."""
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Invalid detail capture deadline")
    job = None
    if os.name == "nt":
        from tools.detail_browser_capture_job import CaptureJob

        job = CaptureJob()
    process = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            start_new_session=os.name != "nt",
        )
        if job:
            # The child reads stdin before importing Playwright or creating a driver.
            job.assign(process.pid)
        try:
            output, _ = process.communicate(request, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise TimeoutError("detail browser capture deadline exceeded") from None
        if process.returncode:
            raise RuntimeError("detail browser capture helper failed")
        return output
    finally:
        deadline = time.monotonic() + CLEANUP_SECONDS
        if process is not None and os.name != "nt":
            from tools.detail_browser_capture_posix import cleanup_capture_session

            cleanup_capture_session(process, deadline=deadline)
        else:
            _cleanup_windows_capture(job, process, deadline=deadline)


def _cleanup_windows_capture(job, process, *, deadline):
    try:
        if job:
            job.close()
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.communicate(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise SystemExit(
                    "detail capture process cleanup did not finish"
                ) from None


def decode_capture_reply(output, *, cdp_endpoint):
    from src.project_environment import EnvironmentAliasConflict
    from tools.live_smoke_context import (
        CdpEndpointUnavailableError,
        DetailChallengeError,
    )

    value = json.loads(output)
    if not isinstance(value, dict):
        raise TypeError("Invalid detail capture reply")
    kind = value.get("kind")
    if kind == "ok":
        result = value.get("result")
        if (
            not isinstance(result, list)
            or len(result) != 4
            or any(type(result[index]) is not str for index in (0, 1, 3))
            or type(result[2]) is not int
            or result[2] < 0
        ):
            raise RuntimeError("Invalid detail capture result")
        return tuple(result)
    if kind == "challenge":
        raise DetailChallengeError(value["operation"], value["challenge_url"])
    if kind == "cdp":
        raise CdpEndpointUnavailableError(
            cdp_endpoint, value["operation"], RuntimeError("capture transport failed")
        )
    if kind == "configuration":
        raise EnvironmentAliasConflict(value["message"])
    raise RuntimeError("detail browser capture failed")


def capture_detail_with_deadline(seed, *, cdp_endpoint):
    from tools.live_smoke_context import CdpEndpointUnavailableError

    request = json.dumps(
        {"seed": seed, "cdp_endpoint": cdp_endpoint}, ensure_ascii=False
    ).encode("utf-8")
    try:
        output = run_capture_process(
            [sys.executable, "-B", "-m", "tools.detail_browser_capture_child"],
            request,
        )
    except TimeoutError as error:
        # Transport failure preserves the item's retry budget; never report a human challenge.
        raise CdpEndpointUnavailableError(
            cdp_endpoint, "detail_browser_capture_deadline", error
        ) from error
    return decode_capture_reply(output, cdp_endpoint=cdp_endpoint)
