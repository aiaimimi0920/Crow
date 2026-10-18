"""Edge native messaging host; stdout is exclusively length-framed JSON."""

import json
import os
import struct
import sys
from pathlib import Path

# Executed by an absolute path, without relying on a browser's working directory.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.project_data_paths import resolve_project_data_root
from tools.desktop_runtime_config import load_runtime_environment
from tools.edge_auth_contract import EXTENSION_ID, MAX_MESSAGE
from tools.edge_auth_store import handle, task_root
from tools.pc1_desktop_recovery import RecoveryError


def exchange(source, sink, handler):
    header = source.read(4)
    if len(header) != 4:
        return
    length = struct.unpack("<I", header)[0]
    if not 0 < length <= MAX_MESSAGE:
        return
    raw = source.read(length)
    try:
        if len(raw) != length:
            raise ValueError
        result = {"ok": True, **handler(json.loads(raw))}
    except RecoveryError as error:
        result = {"ok": False, "code": str(error)}
    except Exception:  # noqa: BLE001 -- protocol boundary must not expose credential-bearing exceptions
        result = {"ok": False, "code": "edge_invalid_request"}
    payload = json.dumps(result, ensure_ascii=True).encode("utf-8")
    sink.write(struct.pack("<I", len(payload)) + payload)
    sink.flush()


def dispatch(message):
    if isinstance(message, dict) and message.get("action") == "ping":
        return {"host": "com.crow.manual_auth", "protocol": 1, "version": "0.1.1"}
    environment = load_runtime_environment(ROOT)
    root = task_root(resolve_project_data_root(ROOT, env=environment))
    return handle(root, message)


def main():
    if len(sys.argv) < 2 or sys.argv[1] != f"chrome-extension://{EXTENSION_ID}/":
        return 1
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    exchange(sys.stdin.buffer, sys.stdout.buffer, dispatch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
