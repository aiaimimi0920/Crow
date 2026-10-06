"""Real helper/driver process trees must stop without touching external processes."""

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.detail_browser_capture import run_capture_process

CHILD = r"""
import json,os,subprocess,sys,time
from pathlib import Path
request=json.load(sys.stdin)
driver=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
Path(request['receipt']).write_text(json.dumps({'helper':os.getpid(),'driver':driver.pid}))
if request['mode']=='body':time.sleep(60)
print(json.dumps({'html':'x'*request.get('size',1)}),flush=True)
if request['mode']=='cleanup':time.sleep(60)
"""


def alive(pid):
    if os.name != "nt":
        return Path(f"/proc/{pid}").exists()  # Zombies are leaks too.
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        assert api.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259
    finally:
        api.CloseHandle(handle)


@pytest.mark.parametrize("mode", ["body", "cleanup", "ok"])
def test_owned_helper_and_driver_are_cleaned_but_external_process_survives(
    tmp_path, mode
):
    external = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    path = tmp_path / "owned-processes.json"
    request = json.dumps({"receipt": str(path), "mode": mode}).encode("utf-8")
    started = time.monotonic()
    try:
        if mode == "ok":
            assert json.loads(
                run_capture_process(
                    [sys.executable, "-c", CHILD], request, timeout_seconds=3
                )
            ) == {"html": "x"}
        else:
            with pytest.raises(TimeoutError, match="deadline exceeded"):
                run_capture_process(
                    [sys.executable, "-c", CHILD], request, timeout_seconds=1
                )
        assert time.monotonic() - started < 7
        assert path.exists(), "The synthetic blocked API must actually have started"
        owned = json.loads(path.read_text())
        until = time.monotonic() + 2
        while any(alive(pid) for pid in owned.values()) and time.monotonic() < until:
            time.sleep(0.05)
        assert not any(alive(pid) for pid in owned.values())
        assert external.poll() is None
    finally:
        external.kill()
        external.wait(timeout=5)


def test_large_html_reply_is_drained_before_waiting_for_exit(tmp_path):
    path = tmp_path / "large-reply.json"
    request = json.dumps(
        {"receipt": str(path), "mode": "ok", "size": 2_000_000}
    ).encode("utf-8")
    output = run_capture_process(
        [sys.executable, "-c", CHILD], request, timeout_seconds=5
    )
    assert len(json.loads(output)["html"]) == 2_000_000


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_deadline_fails_before_starting_a_process(timeout):
    with pytest.raises(ValueError, match="deadline"):
        run_capture_process([], b"", timeout_seconds=timeout)
