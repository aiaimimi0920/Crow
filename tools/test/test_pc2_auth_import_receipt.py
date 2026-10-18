"""Lost acknowledgements must not replay successful imports into the same browser."""

import pytest

from tools import pc2_auth_recovery as recovery
from tools.pc2_auth_import_receipt import (
    browser_instance,
    import_receipt,
    reusable_import,
)


@pytest.mark.parametrize("phase", ["pc2_claimed", "restarting"])
def test_lost_ack_retries_without_importing_again(tmp_path, monkeypatch, phase):
    digest = "a" * 64
    endpoint = "http://browser:9224"
    version = {"webSocketDebuggerUrl": "ws://browser:9224/devtools/browser/one"}
    token = tmp_path / "token"
    token.write_text("test-recovery-token", encoding="utf-8")
    marker = tmp_path / "marker.json"
    imports = []
    active = {"recovery_id": "r1", "status": phase, "snapshot": {"sha256": digest}}
    monkeypatch.setattr(recovery, "ensure_cookie_snapshot", lambda *a, **kw: None)
    monkeypatch.setattr(recovery, "fetch_json", lambda *a, **kw: version)

    def do_import(*args, **kwargs):
        imports.append(True)
        return {
            "sha256": digest,
            "cookie_count": 1,
            "browser_instance": browser_instance(version),
        }

    monkeypatch.setattr(recovery, "import_cookie_snapshot_to_cdp", do_import)
    fail = True

    def poster(url, *args, **kwargs):
        if url.endswith("/heartbeat"):
            return {"ok": True}
        if fail:
            raise OSError("ACK lost")
        return {"ok": True, "status": "verifying"}

    def run():
        return recovery.process_nas_auth_recovery_once(
            "http://nas/api",
            endpoint,
            "pc2",
            tmp_path / "snapshot",
            marker,
            token,
            fetcher=lambda *a, **kw: {"auth_recovery": {"active": active}},
            poster=poster,
        )

    with pytest.raises(OSError, match="ACK lost"):
        run()
    assert marker.exists()
    fail = False
    assert run()["action"] == "recovery_verifying"
    assert len(imports) == 1


@pytest.mark.parametrize(
    "change",
    ["browser", "snapshot", "recovery", "endpoint", "legacy", "missing_identity"],
)
def test_mismatched_receipt_requires_import(change):
    version = {"webSocketDebuggerUrl": "ws://browser:9224/devtools/browser/one"}
    digest, endpoint = "a" * 64, "http://browser:9224"
    marker = import_receipt(
        {
            "sha256": digest,
            "cookie_count": 1,
            "browser_instance": browser_instance(version),
        },
        "r1",
        endpoint,
        100,
    )
    if change == "browser":
        version["webSocketDebuggerUrl"] = "ws://browser:9224/devtools/browser/two"
    elif change == "snapshot":
        marker["snapshot_sha256"] = "b" * 64
    elif change == "recovery":
        marker["recovery_id"] = "r2"
    elif change == "endpoint":
        marker["cdp_endpoint"] = "http://other:9224"
    elif change == "legacy":
        marker["schema_version"] = 1
    else:
        marker.pop("browser_instance")
    assert reusable_import(marker, "r1", digest, endpoint, lambda: version) is None
