"""Detail-only HTTP proof closes the real transaction, never the seed owner."""

from copy import deepcopy

import pytest

from src import auth_cookie_health
from src.runtime_state import RuntimeState
from tools.pc2_solver_auth import _recent_healthy_auth_snapshot

TARGET = "https://sf-item.taobao.com/sf_item/864933660682.htm"
ENDPOINT = "http://192.168.15.20:9224"


@pytest.fixture
def completion_host(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "RUNTIME", RuntimeState())
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(server, "_collection_runtime_state_label", lambda: "test")
    monkeypatch.setattr(
        server,
        "_resolve_auth_cookie_snapshot_path",
        lambda _: str(tmp_path / "cookies.json"),
    )
    monkeypatch.setattr(server, "_cdp_endpoint_permitted", lambda _: True)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_attempts", lambda: 1)
    monkeypatch.setattr(
        server,
        "_export_auth_cdp_cookies",
        lambda _, **_options: [
            {
                "name": "cookie2",
                "value": "synthetic",
                "domain": ".taobao.com",
                "path": "/",
            }
        ],
    )
    monkeypatch.setattr(
        auth_cookie_health, "resolve_cdp_user_agent", lambda _: "test-UA"
    )
    seed_request = {
        "scope": "seed",
        "node_id": "pc2",
        "cdp_endpoint": ENDPOINT,
        "target_url": "https://sf.taobao.com/list/50025969__2.htm",
    }
    seed_id = server._begin_solver_challenge(seed_request)
    server._mark_solver_manual_required(scope="seed", manual_only=True)
    request = {
        "scope": "detail",
        "node_id": "pc2",
        "cdp_endpoint": ENDPOINT,
        "target_url": TARGET,
    }
    detail_id = server._begin_solver_challenge(request)
    server._mark_solver_manual_required(scope="detail", manual_only=True)
    server.RUNTIME.recovery.record_retry(now=100.0, attempted=True)
    seed_receipt = server._solver_scope_state_path("seed").read_bytes()
    budget = server.RUNTIME.recovery.snapshot().retry_attempts
    scheduled = []

    def schedule(payload, completion_id, **kwargs):
        scheduled.append((deepcopy(payload), completion_id, kwargs))
        return server._set_auth_cookie_snapshot_state(
            status="pending",
            completion_id=completion_id,
            refreshed=False,
            auth_state_confirmed=False,
        )

    monkeypatch.setattr(server, "_schedule_auth_cookie_snapshot_refresh", schedule)
    payload = {
        **request,
        "source": "pc2_local_solver",
        "challenge_id": detail_id,
        "completion_id": "detail-scope-completion",
        "refresh_cookie_snapshot": True,
    }
    return server, payload, scheduled, seed_id, seed_receipt, budget, tmp_path


@pytest.mark.parametrize("change", [None, "generation", "target"])
def test_two_phase_detail_completion_preserves_seed_and_budget(
    completion_host, monkeypatch, change
):
    server, payload, scheduled, seed_id, seed_receipt, budget, tmp_path = (
        completion_host
    )

    def probe(*_args, **_kwargs):
        if change:
            state = server._read_solver_scope_state("detail")
            if change == "generation":
                state["challenge_id"] = "replacement-generation"
            else:
                state["last_request"]["target_url"] = TARGET.replace(
                    "864933660682", "999"
                )
            assert server._persist_solver_scope_state("detail", state) is None
        return {"healthy": True}

    monkeypatch.setattr(auth_cookie_health, "probe_detail_page", probe)
    pending = server._collection_observer_auth_complete_payload(payload)
    assert pending["auth_state_confirmed"] is False
    assert (
        pending["auth_confirmation_pending"] is True and pending["scope_paused"] is True
    )
    assert len(scheduled) == 1
    job_payload, completion_id, options = scheduled[0]
    assert options["finalize_auth"] is True
    server._run_auth_cookie_snapshot_retry(job_payload, completion_id, **options)
    snapshot = server._auth_cookie_snapshot_runtime_status()
    assert snapshot["completion_id"] == payload["completion_id"]
    assert snapshot["auth_state_confirmed"] is (change is None)
    if change is None:
        assert snapshot["status"] == "completed" and snapshot["refreshed"] is True
        assert snapshot["result"]["health"]["healthy"] is False
        assert snapshot["result"]["health"]["scope_healthy"] is True
        confirmed = server._collection_observer_auth_complete_payload(payload)
        assert (
            confirmed["auth_state_confirmed"] is True and confirmed["scope"] == "detail"
        )
        for field in (
            "scope_paused",
            "scope_manual_required",
            "scope_force_reset_required",
            "scope_force_unlock_flag_exists",
        ):
            assert confirmed[field] is False
        assert (tmp_path / "cookies.json").exists()
        assert not _recent_healthy_auth_snapshot(
            {
                "last_status": "manual_auth_completed",
                "cookie_snapshot_refresh": snapshot,
            },
            now=snapshot["last_finished_at_epoch"],
        )
    else:
        assert snapshot["status"] == "failed" and snapshot["refreshed"] is False
        assert snapshot["result"]["reason"] == "cookie_snapshot_scope_mismatch"
        assert server._solver_scope_runtime_status("detail")["paused"] is True
        assert not (tmp_path / "cookies.json").exists()
        assert not server._auth_completion_was_confirmed(payload["completion_id"])
    assert server._solver_scope_state_path("seed").read_bytes() == seed_receipt
    seed = server._solver_scope_runtime_status("seed")
    assert seed["challenge_id"] == seed_id and seed["paused"] is True
    assert server.RUNTIME.recovery.snapshot().retry_attempts == budget
