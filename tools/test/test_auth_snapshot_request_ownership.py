"""A single-flight refresh must never lend its proof to another completion."""

import threading
from dataclasses import fields
from types import SimpleNamespace

import pytest

from src.auth_cookie_snapshot_scheduler import schedule_refresh
from src.runtime_state import RuntimeState
from src.server_collection_console import AuthCompletion


@pytest.mark.parametrize("status", ["pending", "completed"])
@pytest.mark.parametrize("changed", ["completion_id", "expected_challenge_id", "scope"])
def test_foreign_active_snapshot_cannot_confirm_or_queue_new_request(
    tmp_path, status, changed
):
    runtime = RuntimeState()
    original = {
        "status": status,
        "completion_id": "new-receipt",
        "expected_challenge_id": "seed-current",
        "scope": "seed",
        "refreshed": status == "completed",
        "auth_state_confirmed": status == "completed",
        "retry_queued": False,
    }
    original[changed] = "detail" if changed == "scope" else "old-owner"
    runtime.cookie_snapshot.replace(original)
    runtime.cookie_snapshot.set_thread(SimpleNamespace(is_alive=lambda: True))
    finalized = []
    pauses = []

    def unexpected(*_args, **_kwargs):
        pytest.fail("unrelated side effect must not run")

    def schedule(payload, completion_id, **options):
        return schedule_refresh(
            payload,
            completion_id,
            state=runtime.cookie_snapshot,
            retry_attempts=unexpected,
            run_retry=unexpected,
            clock=unexpected,
            thread_factory=unexpected,
            **options,
        )

    def finalize(*args, **kwargs):
        finalized.append((args, kwargs))
        return {"auth_state_confirmed": True}

    request = {"scope": "seed", "target_url": "https://example.invalid/seed"}
    dependencies = {field.name: unexpected for field in fields(AuthCompletion)}
    dependencies.update(
        runtime=lambda: runtime,
        normalize_completion=lambda value: value,
        normalize_scope=lambda value: value,
        scope_for_id=lambda _value: None,
        scope_status=lambda _scope: {
            "challenge_id": "seed-current",
            "paused": True,
            "manual_required": True,
            "last_request": request,
        },
        status=lambda: {"paused": True, "last_request": request},
        node_matches=lambda *_args: True,
        was_confirmed=lambda _value: False,
        infer_scope=lambda value: value.get("scope"),
        confirmed=lambda *_args: False,
        flag=lambda payload, key, default: payload.get(key, default),
        manual_only=lambda _value: False,
        set_pause=lambda *args, **kwargs: pauses.append((args, kwargs)),
        schedule=schedule,
        finalize=finalize,
        scope_flag_path=lambda _scope: str(tmp_path / "absent"),
        runtime_label=lambda: "test",
    )
    result = AuthCompletion(**dependencies)._collection_observer_auth_complete_payload(
        {"source": "operator", "scope": "seed", "completion_id": "new-receipt"}
    )

    assert finalized == []
    assert result["auth_state_confirmed"] is False
    assert result["auth_confirmation_pending"] is False
    assert result["ok"] is False
    assert result["scope_paused"] is True
    assert result["cookie_snapshot"]["reason"] == "refresh_already_running"
    assert result["cookie_snapshot"]["retry_queued"] is False
    assert runtime.cookie_snapshot.snapshot() == original
    assert pauses == [((True, "manual_required"), {"scope": "seed"})]


@pytest.mark.parametrize("changed", [None, "expected_challenge_id", "scope"])
def test_completed_receipt_reuse_requires_same_authentication_binding(changed):
    runtime = RuntimeState()
    current = {
        "status": "completed",
        "completion_id": "receipt",
        "expected_challenge_id": "current",
        "scope": "seed",
        "refreshed": True,
    }
    if changed:
        current[changed] = "detail" if changed == "scope" else "previous"
    runtime.cookie_snapshot.replace(current)
    starts = []

    def thread_factory(**options):
        return SimpleNamespace(start=lambda: starts.append(options))

    result = schedule_refresh(
        {"scope": "seed"},
        "receipt",
        state=runtime.cookie_snapshot,
        retry_attempts=lambda: 1,
        run_retry=lambda *_args, **_kwargs: None,
        clock=lambda: 100.0,
        thread_factory=thread_factory,
        finalize_auth=True,
        expected_challenge_id="current",
        completion_request={"scope": "seed"},
    )
    assert result["status"] == ("pending" if changed else "completed")
    assert len(starts) == (1 if changed else 0)


def test_completed_live_worker_returns_busy_until_foreign_request_can_start():
    runtime = RuntimeState()
    published, release = threading.Event(), threading.Event()
    calls = []

    def worker(payload, completion_id, **_options):
        calls.append((payload, completion_id))
        runtime.cookie_snapshot.update({"status": "completed", "refreshed": True})
        published.set()
        assert release.wait(5)

    def schedule(scope, completion_id):
        return schedule_refresh(
            {"scope": scope},
            completion_id,
            state=runtime.cookie_snapshot,
            retry_attempts=lambda: 1,
            run_retry=worker,
            clock=lambda: 100.0,
            thread_factory=threading.Thread,
            finalize_auth=True,
            expected_challenge_id=scope + "-challenge",
            completion_request={"scope": scope},
        )

    assert schedule("detail", "detail-receipt")["status"] == "pending"
    old_thread = runtime.cookie_snapshot.thread
    try:
        assert published.wait(5)
        same = schedule("detail", "detail-receipt")
        assert same["status"] == "completed" and same["refreshed"] is True
        busy = schedule("seed", "seed-receipt")
        assert busy["status"] == "busy" and busy["refreshed"] is False
        assert busy["retry_queued"] is False
        assert calls == [({"scope": "detail"}, "detail-receipt")]
    finally:
        release.set()
        old_thread.join(timeout=5)
    assert not old_thread.is_alive()
    assert schedule("seed", "seed-receipt")["status"] == "pending"
    new_thread = runtime.cookie_snapshot.thread
    new_thread.join(timeout=5)
    assert not new_thread.is_alive()
    assert calls[-1] == ({"scope": "seed"}, "seed-receipt")


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("explicit_legacy", [False, True])
def test_explicit_legacy_scope_is_not_replaced_by_request_hint(active, explicit_legacy):
    runtime = RuntimeState()
    scope = None if explicit_legacy else "seed"
    runtime.cookie_snapshot.replace(
        {
            "status": "completed",
            "completion_id": "receipt",
            "expected_challenge_id": "current",
            "scope": scope,
            "refreshed": True,
        }
    )
    if active:
        runtime.cookie_snapshot.set_thread(SimpleNamespace(is_alive=lambda: True))
    starts = []
    result = schedule_refresh(
        {"scope": None} if explicit_legacy else {},
        "receipt",
        state=runtime.cookie_snapshot,
        retry_attempts=lambda: 1,
        run_retry=lambda *_args, **_kwargs: None,
        clock=lambda: 100.0,
        thread_factory=lambda **options: SimpleNamespace(
            start=lambda: starts.append(options)
        ),
        finalize_auth=True,
        expected_challenge_id="current",
        completion_request={"scope": "seed"},
    )
    assert result["status"] == "completed"
    assert result["scope"] == scope
    assert result["refreshed"] is True
    assert starts == []
