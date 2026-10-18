import io
import json
import struct

from tools import edge_auth_host as host


def test_ping_is_framed_and_does_not_access_runtime_or_task(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("ping must not access configuration, tasks or credentials")

    monkeypatch.setattr(host, "load_runtime_environment", forbidden)
    monkeypatch.setattr(host, "resolve_project_data_root", forbidden)
    monkeypatch.setattr(host, "handle", forbidden)
    raw = json.dumps({"action": "ping"}).encode()
    output = io.BytesIO()
    host.exchange(io.BytesIO(struct.pack("<I", len(raw)) + raw), output, host.dispatch)
    result = output.getvalue()
    assert struct.unpack("<I", result[:4])[0] == len(result[4:])
    assert json.loads(result[4:]) == {
        "ok": True,
        "host": "com.crow.manual_auth",
        "protocol": 1,
        "version": "0.1.1",
    }


def test_ping_still_rejects_unapproved_extension_origin(monkeypatch):
    monkeypatch.setattr(host.sys, "argv", ["host.py", "chrome-extension://other/"])
    assert host.main() == 1
