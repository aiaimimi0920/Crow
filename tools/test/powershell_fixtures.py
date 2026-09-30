"""Reuse a host process for pure fixtures, with a fresh runspace for every case."""

import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def crow_powershell_batch():
    shell = (
        os.environ.get("CROW_TEST_POWERSHELL")
        or shutil.which("pwsh")
        or shutil.which("powershell")
    )
    if not shell:
        pytest.skip("PowerShell unavailable")
    driver = Path(__file__).with_suffix(".ps1")
    process = subprocess.Popen(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(driver)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    responses = queue.Queue()
    diagnostics = []

    def read_responses():
        for line in process.stdout:
            responses.put(line)
        responses.put(None)

    def read_errors():
        diagnostics.extend(process.stderr)

    readers = [
        threading.Thread(target=read_responses, daemon=True),
        threading.Thread(target=read_errors, daemon=True),
    ]
    for reader in readers:
        reader.start()

    def run(arguments, *, cwd=None, timeout=30, **options):
        assert options == {"text": True, "capture_output": True, "check": False}
        assert arguments[1] == "-NoProfile"
        assert len(arguments) == 4 and arguments[2] in ("-File", "-Command")
        request = {
            "mode": arguments[2],
            "source": arguments[3],
            "cwd": str(Path(cwd or Path.cwd()).resolve()),
            "environment": [{"name": k, "value": v} for k, v in os.environ.items()],
        }
        process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
        process.stdin.flush()
        try:
            response = responses.get(timeout=timeout)
        except queue.Empty:
            process.kill()
            raise subprocess.TimeoutExpired(arguments, timeout) from None
        assert response is not None, "PowerShell fixture host exited: " + "".join(
            diagnostics
        )
        result = json.loads(response)
        return subprocess.CompletedProcess(
            arguments, result["code"], result["stdout"], result["stderr"]
        )

    # Keep the ordinary command shape visible in each fixture.
    run.shell = shell
    try:
        yield run
    finally:
        if process.poll() is None:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for reader in readers:
            reader.join(timeout=5)
        process.stdout.close()
        process.stderr.close()
