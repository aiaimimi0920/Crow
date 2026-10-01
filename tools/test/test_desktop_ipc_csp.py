"""原生 IPC 必须可达，同时继续禁止任意明文 HTTP 目标。"""

import json
from pathlib import Path


def test_desktop_csp_allows_native_ipc_without_broad_http_access():
    root = Path(__file__).resolve().parents[2]
    config = json.loads(
        (root / "collector-desktop/src-tauri/tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    directives = config["app"]["security"]["csp"].split(";")
    connect = next(
        row.split()[1:] for row in directives if row.strip().startswith("connect-src ")
    )
    assert "ipc:" in connect
    assert "http://ipc.localhost" in connect
    assert "*" not in connect and "http:" not in connect
