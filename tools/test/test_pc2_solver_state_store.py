"""Fallback state compatibility and failed-write preservation."""

import json

import pytest

from tools import pc2_solver_state_store as store


@pytest.fixture
def state_path(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    monkeypatch.setattr(store, "FALLBACK_STATE_PATH", path)
    return path


def test_native_store_exports_and_fresh_defaults():
    from tools import pc2_local_solver, pc2_solver_fallback

    for name in (
        "_default_fallback_state",
        "_load_fallback_state",
        "_save_fallback_state",
    ):
        original = getattr(store, name)
        assert getattr(pc2_local_solver, name) is original
        assert getattr(pc2_solver_fallback, name) is original
        assert original.__globals__ is vars(store)
    first = store._default_fallback_state()
    second = store._default_fallback_state()
    first["challenge_id"] = "changed"
    assert second["challenge_id"] is None


def test_missing_state_returns_defaults_without_creating_file(state_path):
    assert store._load_fallback_state() == store._default_fallback_state()
    assert not state_path.exists()


@pytest.mark.parametrize(
    "raw",
    [
        b"broken-json",
        b"[]",
        b"null",
        b"\xff",
        b'{"consecutive_failures": 3, "scope": "seed", "slider_attempts": "invalid"}',
    ],
)
def test_bad_state_preserves_bytes_and_returns_all_defaults(state_path, raw):
    state_path.write_bytes(raw)
    assert store._load_fallback_state() == store._default_fallback_state()
    assert state_path.read_bytes() == raw


def test_legacy_state_normalizes_and_keeps_pending_identity(state_path):
    state_path.write_text(
        json.dumps(
            {
                "consecutive_failures": "4",
                "window_started_at": "100.5",
                "terminal_manual_next_report": "120",
                "auth_complete_pending": True,
                "auth_completion_id": " completion-1 ",
                "collection_resume_pending": True,
                "collection_resume_request_id": " resume-1 ",
                "challenge_id": " challenge-1 ",
                "scope": " detail ",
                "unknown_field": "ignored",
            }
        ),
        encoding="utf-8",
    )
    state = store._load_fallback_state()
    assert state["slider_attempts"] == state["consecutive_failures"] == 4
    assert state["window_started_at"] == 100.5
    assert state["terminal_manual_next_report"] == 120.0
    assert state["auth_complete_pending"] is True
    assert state["auth_completion_id"] == "completion-1"
    assert state["collection_resume_pending"] is True
    assert state["collection_resume_request_id"] == "resume-1"
    assert state["challenge_id"] == "challenge-1"
    assert state["scope"] == "detail"
    assert "unknown_field" not in state


def test_atomic_save_replaces_only_after_complete_serialization(
    monkeypatch, state_path
):
    previous = b'{"challenge_id":"previous"}'
    state_path.write_bytes(previous)
    state = store._default_fallback_state()
    state.update(challenge_id="next", scope="seed", slider_attempts=3)
    replace = store.os.replace
    observed = []

    def checked_replace(source, destination):
        assert destination == state_path
        assert source.parent == destination.parent
        assert destination.read_bytes() == previous
        assert json.loads(source.read_text(encoding="utf-8")) == state
        observed.append(source)
        replace(source, destination)

    monkeypatch.setattr(store.os, "replace", checked_replace)
    store._save_fallback_state(state)
    assert len(observed) == 1
    assert not observed[0].exists()
    assert json.loads(state_path.read_text(encoding="utf-8")) == state


@pytest.mark.parametrize("failure", ["serialize", "replace"])
def test_failed_save_retains_previous_file_and_cleans_temporary(
    monkeypatch, state_path, failure
):
    previous = b'{"challenge_id":"previous"}'
    state_path.write_bytes(previous)
    events = []
    monkeypatch.setattr(store, "log_event", events.append)
    state = store._default_fallback_state()
    if failure == "serialize":
        state["unsupported"] = object()
    else:

        def failed_replace(*_args):
            raise OSError("replace denied")

        monkeypatch.setattr(store.os, "replace", failed_replace)
    store._save_fallback_state(state)
    assert state_path.read_bytes() == previous
    assert list(state_path.parent.glob("*.tmp")) == []
    assert len(events) == 1
    assert events[0]["kind"] == "fallback_state_save_error"
