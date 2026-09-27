"""Recovery snapshot reads authorize before state/file access and enforce limits."""

import base64
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_snapshot_download_bounds_read_before_rejecting_oversized_file(monkeypatch):
    from src import server

    limit = 5 * 1024 * 1024
    reads = []

    class TrackedStream(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    stream = TrackedStream(b"x" * (limit + 64))
    opened = Mock(return_value=stream)
    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(
        server, "_nas_auth_recovery_authorized", lambda headers: (True, "")
    )
    monkeypatch.setattr(
        server,
        "_resolve_auth_cookie_snapshot_path",
        lambda payload: "synthetic-snapshot",
    )
    state = {
        "active": {
            "recovery_id": "r",
            "status": "snapshot_ready",
            "snapshot": {"sha256": "f" * 64},
        }
    }
    monkeypatch.setattr(
        server, "NAS_AUTH_RECOVERY", SimpleNamespace(snapshot=lambda: state)
    )
    handler = SimpleNamespace(headers={}, send_json=Mock(), send_error_json=Mock())
    server._get_auth_recovery_snapshot(handler, None, "unused", {"recovery_id": ["r"]})
    assert reads == [limit + 1]
    opened.assert_called_once_with("rb")
    assert stream.closed
    assert (
        handler.send_error_json.call_args.kwargs["code"]
        == "COLLECTION_AUTH_RECOVERY_SNAPSHOT_INVALID"
    )
    handler.send_json.assert_not_called()


def test_native_recovery_read_descriptors():
    from src import auth_recovery_read_handlers, server

    handler = object.__new__(server.DataHandler)
    for name in auth_recovery_read_handlers.RecoveryReadHandlers.__all__:
        method = getattr(handler, name)
        assert method.__self__ is handler
        assert method.__func__ is getattr(server, name)
        assert method.__module__ == auth_recovery_read_handlers.__name__
        assert getattr(server._CONTEXT, name) is method.__func__


@pytest.mark.parametrize("name", ["_get_auth_recovery", "_get_auth_recovery_snapshot"])
def test_unauthorized_read_cannot_access_state_or_path(monkeypatch, name):
    from src import server

    manager = SimpleNamespace(snapshot=Mock())
    resolve = Mock()
    handler = SimpleNamespace(headers={}, send_json=Mock(), send_error_json=Mock())
    monkeypatch.setattr(
        server, "_nas_auth_recovery_authorized", lambda headers: (False, "denied")
    )
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", manager)
    monkeypatch.setattr(server, "_resolve_auth_cookie_snapshot_path", resolve)
    getattr(server, name)(handler, None, "unused", {"recovery_id": ["r"]})
    manager.snapshot.assert_not_called()
    resolve.assert_not_called()
    assert handler.send_error_json.call_args.kwargs["status"] == 403
    handler.send_json.assert_not_called()


@pytest.mark.parametrize("extra", [0, 1])
def test_snapshot_exact_size_boundary_and_live_dependencies(
    monkeypatch, tmp_path, extra
):
    from src import server

    raw = b"x" * (5 * 1024 * 1024 + extra)
    digest = hashlib.sha256(raw).hexdigest()
    path = tmp_path / "synthetic-snapshot"
    path.write_bytes(raw)
    snapshot = {
        "active": {
            "recovery_id": "r",
            "status": "snapshot_ready",
            "snapshot": {"sha256": digest.upper()},
        }
    }
    manager = SimpleNamespace(snapshot=Mock(return_value=snapshot))
    handler = SimpleNamespace(headers={}, send_json=Mock(), send_error_json=Mock())
    saved = server._get_auth_recovery_snapshot
    monkeypatch.setattr(
        server, "_nas_auth_recovery_authorized", lambda headers: (True, "")
    )
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", manager)
    resolve = Mock(return_value=path)
    monkeypatch.setattr(server, "_resolve_auth_cookie_snapshot_path", resolve)
    saved(handler, None, "unused", {"recovery_id": [" r "]})
    resolve.assert_called_once_with({"node_id": "pc2"})
    if extra:
        assert (
            handler.send_error_json.call_args.kwargs["code"]
            == "COLLECTION_AUTH_RECOVERY_SNAPSHOT_INVALID"
        )
        handler.send_json.assert_not_called()
    else:
        result = handler.send_json.call_args.args[0]
        assert result["sha256"] == digest
        assert base64.b64decode(result["snapshot"]) == raw
        handler.send_error_json.assert_not_called()
