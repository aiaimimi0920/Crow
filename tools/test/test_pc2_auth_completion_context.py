"""PC2 completion metadata must let NAS resolve the correct node snapshot."""

from pathlib import Path

import pytest

from src.auth_cookie_paths import AuthCookiePaths
from tools import pc2_solver_auth as auth


@pytest.mark.parametrize("node", ["pc2", "pc2-secondary"])
def test_completion_payload_resolves_node_snapshot_without_nas_node_default(
    monkeypatch, tmp_path, node
):
    monkeypatch.setenv("FAPAI_NODE_ID", " " + node + " ")
    monkeypatch.setenv("FAPAI_REPORT_CDP_ENDPOINT", "http://pc2.example:9224")
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://127.0.0.1:9223")
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 1)
    paths = AuthCookiePaths(
        env=lambda _key, default=None: default,
        repo_root=lambda: tmp_path,
        data_dir=lambda: str(tmp_path / "datas"),
        normalize_node=lambda value: str(value or "").strip(),
        roots=lambda: [tmp_path],
    )
    calls = []

    def post(url, payload, *, timeout):
        calls.append(payload)
        return {"ok": True}

    monkeypatch.setattr(auth, "post_json", post)
    auth.notify_auth_complete(
        "https://nas.example/api",
        completion_id="completion-current",
        challenge_id="challenge-current",
        scope="seed",
    )
    assert len(calls) == 1
    payload = calls[0]
    resolved = paths._resolve_auth_cookie_snapshot_path(payload)
    assert resolved, "NAS cannot finalize authentication without a node snapshot path"
    assert (
        Path(resolved) == tmp_path / "secrets" / "nodes" / node / "taobao-cookies.json"
    )
    assert payload["cdp_endpoint"] == "http://pc2.example:9224"
    assert payload["scope"] == "seed"
    assert payload["challenge_id"] == "challenge-current"
    assert payload["completion_id"] == "completion-current"


def test_completion_does_not_send_pc2_private_loopback_to_nas(monkeypatch):
    monkeypatch.delenv("FAPAI_NODE_ID", raising=False)
    monkeypatch.delenv("FAPAI_REPORT_CDP_ENDPOINT", raising=False)
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://127.0.0.1:9223")
    monkeypatch.setattr(auth, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 1)
    calls = []
    monkeypatch.setattr(
        auth,
        "post_json",
        lambda _url, payload, **_kwargs: calls.append(payload) or {"ok": True},
    )
    auth.notify_auth_complete("https://nas.example/api")
    assert calls[0]["node_id"] == "pc2"
    assert "cdp_endpoint" not in calls[0]
