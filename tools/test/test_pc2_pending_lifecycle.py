"""Native notification ownership and persisted completion handoff."""

import pytest

from tools import pc2_solver_auth_pending as pending
from tools import pc2_solver_fallback as fallback
from tools import pc2_solver_state_store as store


def test_pending_entrypoints_keep_original_owner_globals():
    from tools import pc2_local_solver

    for owner in (pending, fallback):
        for name in owner.__all__:
            value = getattr(owner, name)
            if callable(value) and value.__module__ == owner.__name__:
                assert getattr(pc2_local_solver, name) is value
                assert value.__globals__ is vars(owner)


def test_success_handoff_persists_rotated_owned_challenge_before_notification(
    monkeypatch,
):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    monkeypatch.setattr(pending, "log_event", lambda _event: None)
    target = "https://sf.taobao.com/list/200782003__2.htm"
    latest = {
        "challenge_id": "new",
        "manual_only": False,
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://127.0.0.1:9223",
            "target_url": target,
        },
    }
    monkeypatch.setattr(pending, "read_solver_status", lambda _api: latest)
    state = store._default_fallback_state()
    state.update(
        challenge_id="old",
        slider_attempts=7,
        slider_attempt_started_at=100.0,
        collection_resume_pending=True,
        collection_resume_request_id="obsolete",
    )
    store._save_fallback_state(state)
    calls = []

    def notify(_api, **payload):
        persisted = store._load_fallback_state()
        assert persisted["challenge_id"] == payload["challenge_id"] == "new"
        assert persisted["auth_completion_id"] == payload["completion_id"]
        assert persisted["auth_complete_pending"] is True
        assert persisted["slider_attempt_started_at"] is None
        assert persisted["slider_attempts"] == 7
        assert persisted["collection_resume_pending"] is False
        assert persisted["collection_resume_request_id"] is None
        assert payload["scope"] == "seed"
        calls.append(payload)
        return {"error": "timeout", "request_attempts": 2}

    monkeypatch.setattr(pending, "notify_auth_complete", notify)
    result = pending.confirm_local_solver_success(
        "https://nas/api",
        {"challenge_id": "old"},
        target,
        "http://127.0.0.1:9223",
        "pc2",
    )
    assert len(calls) == 1
    assert result["pending"] is True and result["confirmed"] is False
    persisted = store._load_fallback_state()
    assert persisted["auth_complete_attempts"] == 2
    assert persisted["auth_complete_last_error"] == "timeout"
    assert persisted["auth_completion_id"] == calls[0]["completion_id"]


@pytest.mark.parametrize("fails", [False, True])
def test_manual_report_preserves_payload_and_failure_envelope(monkeypatch, fails):
    monkeypatch.setenv("FAPAI_NODE_ID", " pc2 ")
    calls = []

    def post(url, payload, *, timeout):
        calls.append((url, payload, timeout))
        if fails:
            raise OSError("offline")
        return {"accepted": True}

    monkeypatch.setattr(fallback, "post_json", post)
    result = fallback._report_manual_captcha(
        "https://nas/api/", "http://127.0.0.1:9223", None
    )
    assert len(calls) == 1
    url, payload, timeout = calls[0]
    assert url == "https://nas/api/report_manual_captcha"
    assert timeout == 10
    assert payload["url"] == ""
    assert payload["node_id"] == "pc2"
    assert payload["manual_only"] is True
    assert payload["cdp_endpoint"] == "http://127.0.0.1:9223"
    assert isinstance(payload["timestamp"], int)
    assert result == ({"error": "OSError('offline')"} if fails else {"accepted": True})
