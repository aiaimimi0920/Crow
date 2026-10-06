"""Bounded cleanup of one private capture session, including adopted zombies."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _session_members(session_id):
    members = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if int(fields[2]) == session_id and int(fields[3]) == session_id:
            members[int(path.name)] = fields[19]  # Linux starttime guards PID reuse.
    return members


def _same_process(pid, starttime):
    try:
        fields = Path("/proc", str(pid), "stat").read_text().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return False
    return fields[19] == starttime


def cleanup_capture_session(process, *, deadline):
    """Never waitpid(-1): reap only descendants from this helper's own session."""
    linux = sys.platform.startswith("linux")
    members = _session_members(process.pid) if linux else {}
    if members or not linux:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    # Include a child forked between the first snapshot and the group kill.
    if linux:
        members.update(_session_members(process.pid))
    try:
        process.communicate(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        raise SystemExit("detail capture process cleanup did not finish") from None
    while members:
        remaining = {}
        for pid, starttime in members.items():
            if not _same_process(pid, starttime):
                continue
            try:
                # Container PID 1 adopts the helper's orphaned driver children.
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass  # A non-PID-1 host reaper owns this child instead.
            if _same_process(pid, starttime):
                remaining[pid] = starttime
        members = remaining
        if members:
            if time.monotonic() >= deadline:
                raise SystemExit("detail capture descendants were not reaped")
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
