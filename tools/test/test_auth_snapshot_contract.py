"""PC1 publishing and NAS downloads share immutable path and exception identity."""

import base64
import builtins
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.auth_snapshot_contract import RecoveryError, snapshot_path


def test_nas_manual_snapshot_download_does_not_import_tools(tmp_path, monkeypatch):
    from src.auth_recovery_read_handlers import bind_recovery_reads

    recovery_id = "auth-recovery-" + "a" * 32
    raw = b"synthetic snapshot"
    digest = hashlib.sha256(raw).hexdigest()
    base = tmp_path / "cookies.json"
    path = snapshot_path(base, recovery_id, digest)
    path.parent.mkdir()
    path.write_bytes(raw)
    state = {
        "active": {
            "recovery_id": recovery_id,
            "manual_request_id": "manual",
            "status": "snapshot_ready",
            "snapshot": {"sha256": digest},
        }
    }
    host = SimpleNamespace(
        NAS_AUTH_RECOVERY=SimpleNamespace(snapshot=lambda: state),
        _nas_auth_recovery_authorized=lambda headers: (True, ""),
        _resolve_auth_cookie_snapshot_path=lambda payload: base,
    )
    handler = SimpleNamespace(headers={}, send_json=Mock(), send_error_json=Mock())
    original_import = builtins.__import__

    def without_tools(name, *args, **kwargs):
        if name == "tools" or name.startswith("tools."):
            raise AssertionError("NAS snapshot read imported desktop tools")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_tools)
    bind_recovery_reads(host)._get_auth_recovery_snapshot(
        handler, None, "unused", {"recovery_id": [recovery_id]}
    )
    assert base64.b64decode(handler.send_json.call_args.args[0]["snapshot"]) == raw
    handler.send_error_json.assert_not_called()


def test_existing_tool_exports_share_contract_identity():
    from tools import manual_auth_snapshot, pc1_desktop_recovery

    assert manual_auth_snapshot.snapshot_path is snapshot_path
    assert manual_auth_snapshot.RecoveryError is RecoveryError
    assert pc1_desktop_recovery.RecoveryError is RecoveryError


@pytest.mark.parametrize("base", ["cookies.json", "profiles/pc2/cookies.json"])
def test_snapshot_path_is_immutable_sibling(base):
    recovery_id = "auth-recovery-" + "a" * 32
    digest = "b" * 64
    assert (
        snapshot_path(base, recovery_id, digest)
        == Path(base).parent / "desktop-auth" / f"{recovery_id}-{digest}.json"
    )


@pytest.mark.parametrize(
    "recovery_id,digest,code",
    [
        ("../escape", "b" * 64, "invalid_request"),
        ("auth-recovery-" + "A" * 32, "b" * 64, "invalid_request"),
        ("auth-recovery-" + "a" * 31, "b" * 64, "invalid_request"),
        ("auth-recovery-" + "a" * 32, "../escape", "invalid_snapshot"),
        ("auth-recovery-" + "a" * 32, "B" * 64, "invalid_snapshot"),
        ("auth-recovery-" + "a" * 32, "b" * 63, "invalid_snapshot"),
    ],
)
def test_snapshot_path_rejects_untrusted_names(recovery_id, digest, code):
    with pytest.raises(RecoveryError, match=f"^{code}$"):
        snapshot_path("cookies.json", recovery_id, digest)
