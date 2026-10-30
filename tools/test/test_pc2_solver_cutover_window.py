import copy
import json

import pytest

from tools import pc2_solver_cutover_window as cutover
from tools.pc2_solver_cutover_window import CutoverWindow, manual_window_admission


@pytest.fixture
def inputs():
    request = {"request_id": "a" * 32, "requested_at": 100, "expires_at": 700}
    return {
        "expected": request,
        "request": dict(request),
        "ack": {
            "request_id": "a" * 32,
            "expires_at": 700,
            "status": "active",
            "solver_pid": 42,
        },
        "heartbeat": {"phase": "manual_window", "pid": 42, "updated_at_epoch": 150},
        "state": {
            "auth_complete_pending": False,
            "collection_resume_pending": False,
            "terminal_manual_pending": False,
            "solver_cooldown_until": 800,
        },
        "status": {"running": False, "global_manual_pause_active": False},
        "solver_pids": [42],
        "child_busy": False,
        "now": 150,
        "minimum_remaining": 420,
    }


def test_complete_iteration_ack_is_admitted_without_changing_backpressure(inputs):
    before = copy.deepcopy(inputs)
    assert manual_window_admission(**inputs)["eligible"]
    assert inputs == before


@pytest.mark.parametrize(
    "field,patch",
    [
        ("request", {"request_id": "b" * 32}),
        ("request", {"expires_at": 701}),
        ("ack", {"request_id": "b" * 32}),
        ("ack", {"expires_at": 701}),
        ("ack", {"solver_pid": 43}),
        ("ack", {"status": "inactive"}),
        ("heartbeat", {"pid": 43}),
        ("heartbeat", {"updated_at_epoch": 99}),
        ("heartbeat", {"updated_at_epoch": 140}),
        ("heartbeat", {"updated_at_epoch": 151}),
        ("heartbeat", {"updated_at_epoch": float("nan")}),
        ("heartbeat", {"phase": "polling"}),
        ("state", {"auth_complete_pending": True}),
        ("state", {"collection_resume_pending": True}),
        ("state", {"terminal_manual_pending": True}),
        ("state", {"auth_complete_pending": None}),
        ("state", {"slider_attempt_started_at": 149}),
        ("status", {"running": True}),
        ("status", {"queued": True}),
        ("status", {"nas_solver_active": True}),
        ("status", {"global_manual_pause_active": True}),
        ("status", {"operator_paused": True}),
        ("status", {"error": "unavailable"}),
    ],
)
def test_mismatched_stale_or_pending_state_is_rejected(inputs, field, patch):
    inputs[field].update(patch)
    assert not manual_window_admission(**inputs)["eligible"]


@pytest.mark.parametrize(
    "patch",
    [
        {"child_busy": True},
        {"child_busy": None},
        {"solver_pids": []},
        {"solver_pids": [42, 43]},
        {"solver_pids": [True]},
        {"now": 700},
        {"minimum_remaining": 551},
        {"minimum_remaining": 0},
        {"now": float("inf")},
        {"expected": {}},
        {"state": None},
        {"status": {}},
        {"ack": None},
    ],
)
def test_unknown_or_unbounded_proof_is_rejected(inputs, patch):
    inputs.update(patch)
    assert not manual_window_admission(**inputs)["eligible"]


def test_publish_and_release_only_own_request_without_deleting_history(tmp_path):
    path = tmp_path / "solver-manual-window.json"
    previous = b'{"expires_at": 1}\n'
    path.write_bytes(previous)
    owner = CutoverWindow(path)
    request = owner.begin(100)
    assert owner.previous == previous
    assert request["expires_at"] == 700
    assert json.loads(path.read_bytes()) == request
    assert owner.release(150)
    assert json.loads(path.read_bytes())["expires_at"] == 150
    assert not owner.release(151)
    assert path.exists()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"expires_at": 101}',
        b'{"expires_at": true}',
        b'{"expires_at": "1"}',
        b"null",
        b"not json",
        b"{}",
        b"x" * 4097,
    ],
)
def test_active_or_unreadable_foreign_request_is_never_overwritten(tmp_path, raw):
    path = tmp_path / "request.json"
    path.write_bytes(raw)
    with pytest.raises((ValueError, RuntimeError)):
        CutoverWindow(path).begin(100)
    assert path.read_bytes() == raw


def test_lost_ownership_is_not_released_or_overwritten(tmp_path):
    path = tmp_path / "request.json"
    owner = CutoverWindow(path)
    owner.begin(100)
    foreign = b'{"request_id":"other owner","expires_at": 200}'
    path.write_bytes(foreign)
    assert not owner.release(150)
    assert path.read_bytes() == foreign


def test_failed_activation_releases_window_and_preserves_solver_files(tmp_path):
    path = tmp_path / "request.json"
    state = tmp_path / "solver-fallback-state.json"
    state.write_bytes(b'{"slider_attempts":3,"solver_cooldown_until":900}')
    before = state.read_bytes()
    owner = CutoverWindow(path)
    owner.begin(100)
    try:
        raise RuntimeError("candidate failed")
    except RuntimeError:
        pass
    finally:
        assert owner.release(150)
    assert state.read_bytes() == before


def test_publish_rechecks_owner_after_staging(tmp_path, monkeypatch):
    path = tmp_path / "request.json"
    owner = CutoverWindow(path)
    # Simulate an owner appearing during publication, before the final compare.
    monkeypatch.setattr(
        cutover.os, "fsync", lambda _: path.write_bytes(b'{"expires_at": 999}')
    )
    with pytest.raises(RuntimeError, match="owner changed"):
        owner.begin(100)
    assert path.read_bytes() == b'{"expires_at": 999}'


def test_maximum_duration_matches_installed_gate_contract():
    from tools.pc2_solver_manual_window import MAX_WINDOW_SECONDS

    assert MAX_WINDOW_SECONDS == 600
