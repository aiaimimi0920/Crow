"""Desktop adapter for the manually paired Edge extension."""

import os
import subprocess
from pathlib import Path

from tools.edge_auth_contract import EXTENSION_ID
from tools.edge_auth_store import capture, create_task, task_root
from tools.pc1_desktop_recovery import RecoveryError


def open_edge(*, data_root, request_id, url, scope, api, challenge_id):
    # No user-data-dir, debugging flags, process termination or profile copying.
    paths = [
        Path(os.environ.get(key, "")) / "Microsoft/Edge/Application/msedge.exe"
        for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
    ]
    browser = next((path for path in paths if path.is_file()), None)
    if browser is None:
        raise RecoveryError("edge_unavailable")
    create_task(
        task_root(data_root),
        request_id=request_id,
        url=url,
        scope=scope,
        api=api,
        challenge_id=challenge_id,
    )
    subprocess.Popen(
        [str(browser), f"chrome-extension://{EXTENSION_ID}/auth.html"],
        cwd=str(browser.parent),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {
        "phase": "ready_for_human",
        "code": "edge_ready",
        "target_id": "edge:" + request_id,
    }


def capture_edge(data_root, client, request_id, scope, url, challenge_id):
    return capture(
        task_root(data_root),
        request_id=request_id,
        api=client.url,
        scope=scope,
        url=url,
        challenge_id=challenge_id,
    )
