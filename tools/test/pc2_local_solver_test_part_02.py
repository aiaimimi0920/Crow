from tools import pc2_solver_fallback, pc2_solver_retry_state, pc2_solver_state_store
from tools import pc2_solver_execution
from tools.test.pc2_local_solver_test_context import *


def test_solver_cooldown_starts_after_configured_failures(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    state["slider_attempts"] = 3
    monkeypatch.setattr(pc2_solver_retry_state, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 3)
    monkeypatch.setattr(pc2_solver_retry_state, "SOLVER_COOLDOWN_SECONDS", 600.0)

    assert pc2_local_solver._begin_solver_cooldown_if_needed(state, now=1000.0) is True
    assert state["solver_cooldown_until"] == 1600.0
    assert state["solver_cooldown_reason"] == "repeated_solver_failures"


def test_slider_rule_supports_ten_attempts_five_second_spacing_and_180_second_cooldown(
    monkeypatch,
) -> None:
    state = pc2_local_solver._default_fallback_state()
    monkeypatch.setattr(pc2_solver_retry_state, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 10)
    monkeypatch.setattr(pc2_solver_retry_state, "SOLVER_COOLDOWN_SECONDS", 180.0)
    monkeypatch.setattr(pc2_solver_retry_state, "SLIDER_RETRY_INTERVAL_SECONDS", 5.0)

    for attempt in range(1, 10):
        result = pc2_local_solver._record_slider_attempt_failure(
            state, now=1000.0 + (attempt - 1) * 5
        )
        assert result["attempts"] == attempt
        assert result["cooldown_started"] is False
        assert state["slider_next_attempt_at"] == 1000.0 + attempt * 5
        assert state["solver_cooldown_until"] is None

    tenth = pc2_local_solver._record_slider_attempt_failure(state, now=1045.0)
    assert tenth["attempts"] == 10
    assert tenth["cooldown_started"] is True
    assert state["slider_next_attempt_at"] is None
    assert state["solver_cooldown_until"] == 1225.0


def test_solver_blocked_report_retries_once_and_latches_success(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "challenge_id": "captcha-detail",
            "scope": "detail",
            "slider_attempts": 10,
            "consecutive_failures": 10,
            "solver_cooldown_until": 1180.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    responses = iter(
        [
            {"ok": False, "error": "temporary"},
            {"status": "node_solver_blocked", "captcha_solver": {}},
        ]
    )
    calls: list[float] = []
    monkeypatch.setattr(
        pc2_solver_fallback,
        "notify_solver_blocked",
        lambda *_args, **_kwargs: calls.append(1.0) or next(responses),
    )
    monkeypatch.setattr(
        pc2_solver_fallback, "_save_fallback_state", lambda _state: None
    )
    solver_status = {"challenge_id": "captcha-detail", "scope": "detail"}

    first = pc2_local_solver._retry_node_solver_blocked_report(
        "http://collector/api", solver_status, state, now=1000.0
    )
    early = pc2_local_solver._retry_node_solver_blocked_report(
        "http://collector/api", solver_status, state, now=1004.0
    )
    second = pc2_local_solver._retry_node_solver_blocked_report(
        "http://collector/api", solver_status, state, now=1005.0
    )
    latched = pc2_local_solver._retry_node_solver_blocked_report(
        "http://collector/api", solver_status, state, now=1006.0
    )

    assert first["attempted"] is True
    assert first["confirmed"] is False
    assert early["attempted"] is False
    assert second["confirmed"] is True
    assert latched == {"attempted": False, "confirmed": True, "state": state}
    assert len(calls) == 2
    assert state["node_solver_blocked_reported"] is True
    assert state["node_solver_blocked_report_attempts"] == 2
    assert state["node_solver_blocked_report_next_retry_at"] is None


def test_solver_blocked_report_rejects_rotated_challenge(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "challenge_id": "captcha-old",
            "scope": "detail",
            "solver_cooldown_until": 1180.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    calls: list[object] = []
    monkeypatch.setattr(
        pc2_solver_fallback,
        "notify_solver_blocked",
        lambda *_args, **_kwargs: calls.append(object()),
    )

    result = pc2_local_solver._retry_node_solver_blocked_report(
        "http://collector/api",
        {"challenge_id": "captcha-new", "scope": "detail"},
        state,
        now=1000.0,
    )

    assert result["attempted"] is False
    assert result["reason"] == "challenge_mismatch"
    assert calls == []


def test_solver_attempt_progress_is_persisted_and_completed_on_failure(
    monkeypatch,
) -> None:
    state = pc2_local_solver._default_fallback_state()
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(
        pc2_solver_retry_state,
        "_save_fallback_state",
        lambda value: saved.append(dict(value)),
    )

    pc2_local_solver._record_slider_attempt_started(state, now=1000.0)

    assert state["slider_attempt_started_at"] == 1000.0
    assert state["slider_last_progress_at"] == 1000.0
    assert saved[-1]["slider_attempt_started_at"] == 1000.0

    pc2_local_solver._record_slider_attempt_failure(state, now=1075.0)

    assert state["slider_attempt_started_at"] is None
    assert state["slider_last_progress_at"] == 1075.0


def test_slider_retry_does_not_run_before_twenty_second_deadline() -> None:
    state = pc2_local_solver._default_fallback_state()
    state["slider_next_attempt_at"] = 1020.0

    assert pc2_local_solver._slider_retry_due(state, now=1019.9) is False
    assert pc2_local_solver._slider_retry_due(state, now=1020.0) is True


def test_new_challenge_id_resets_previous_retry_window(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        pc2_solver_state_store, "FALLBACK_STATE_PATH", tmp_path / "state.json"
    )
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "challenge_id": "challenge-a",
            "slider_attempts": 9,
            "consecutive_failures": 9,
            "slider_next_attempt_at": 2000.0,
            "node_solver_blocked_reported": True,
            "node_solver_blocked_report_attempts": 1,
        }
    )

    synced, reset = pc2_local_solver._sync_challenge_state(state, "challenge-b")

    assert reset is True
    assert synced["challenge_id"] == "challenge-b"
    assert synced["slider_attempts"] == 0
    assert synced["consecutive_failures"] == 0
    assert synced["slider_next_attempt_at"] is None
    assert synced["node_solver_blocked_reported"] is False
    assert synced["node_solver_blocked_report_attempts"] == 0


def test_select_solver_scope_status_keeps_preferred_challenge() -> None:
    status = {
        "challenge_id": "seed-newest",
        "last_request": {"target_url": "https://sf.taobao.com/list/new.htm"},
        "scopes": {
            "seed": {
                "challenge_id": "seed-newest",
                "first_seen_epoch": 200.0,
                "paused": True,
                "last_status": "running",
                "last_request": {"target_url": "https://sf.taobao.com/list/new.htm"},
            },
            "detail": {
                "challenge_id": "detail-active",
                "first_seen_epoch": 100.0,
                "paused": True,
                "last_status": "running",
                "last_request": {
                    "target_url": "https://sf-item.taobao.com/sf_item/1.htm"
                },
            },
        },
    }

    selected = pc2_local_solver.select_solver_scope_status(
        status,
        preferred_challenge_id="detail-active",
    )

    assert selected["scope"] == "detail"
    assert selected["challenge_id"] == "detail-active"
    assert selected["last_request"]["target_url"].startswith(
        "https://sf-item.taobao.com/"
    )


def test_select_solver_scope_status_uses_oldest_challenge_without_preference() -> None:
    status = {
        "scopes": {
            "seed": {
                "challenge_id": "seed-newer",
                "first_seen_epoch": 200.0,
                "paused": True,
                "last_request": {"target_url": "https://sf.taobao.com/list/new.htm"},
            },
            "detail": {
                "challenge_id": "detail-older",
                "first_seen_epoch": 100.0,
                "paused": True,
                "last_request": {
                    "target_url": "https://sf-item.taobao.com/sf_item/1.htm"
                },
            },
        }
    }

    selected = pc2_local_solver.select_solver_scope_status(status)

    assert selected["scope"] == "detail"
    assert selected["challenge_id"] == "detail-older"


def test_fallback_state_round_trip_preserves_scope(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        pc2_solver_state_store, "FALLBACK_STATE_PATH", tmp_path / "state.json"
    )
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {"challenge_id": "detail-active", "scope": "detail", "slider_attempts": 4}
    )
    pc2_local_solver._save_fallback_state(state)

    loaded = pc2_local_solver._load_fallback_state()

    assert loaded["scope"] == "detail"
    assert loaded["challenge_id"] == "detail-active"
    assert loaded["slider_attempts"] == 4


def test_run_solver_local_allows_two_profile_replays_within_one_attempt(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeSolver:
        last_failure_reason = None

        def __init__(self, **kwargs) -> None:
            calls.append({"init": kwargs})

        def _remember_target_tab(self, tab: dict[str, object]) -> None:
            calls.append({"remember": tab})

        def solve(self, **kwargs) -> bool:
            calls.append({"solve": kwargs})
            return True

    monkeypatch.setattr(pc2_solver_execution, "_solver_class", lambda: FakeSolver)

    probe_target = {
        "_target_id": "slider-target",
        "_target_url": "https://example.test/visible-slider",
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/slider-target",
    }

    assert (
        pc2_local_solver.run_solver_local(
            "http://127.0.0.1:9223",
            "https://example.test/requested-page-3",
            max_attempts=50,
            probe_target=probe_target,
            drag_profile_offset=2,
        )
        is True
    )
    assert calls[1] == {
        "remember": {
            "id": "slider-target",
            "url": "https://example.test/visible-slider",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/slider-target",
        }
    }
    assert calls[-1] == {
        "solve": {
            "max_attempts": 1,
            "nc_retry_replay_limit": 2,
            "slider_find_max_retries": 1,
            "drag_profile_offset": 2,
        }
    }


def test_run_solver_local_with_deadline_returns_child_result(monkeypatch) -> None:
    messages: list[dict[str, object]] = []
    process_state: dict[str, object] = {}

    class Receiver:
        def poll(self) -> bool:
            return bool(messages)

        def recv(self):
            return messages.pop(0)

        def close(self) -> None:
            process_state["receiver_closed"] = True

    class Sender:
        def send(self, payload) -> None:
            messages.append(payload)

        def close(self) -> None:
            process_state["sender_closed"] = True

    class Process:
        exitcode = 0

        def __init__(self, *, target, args, name) -> None:
            self.target = target
            self.args = args
            process_state["name"] = name

        def start(self) -> None:
            self.target(*self.args)

        def join(self, timeout) -> None:
            process_state["join_timeout"] = timeout

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            process_state["process_closed"] = True

    class Context:
        def Pipe(self, *, duplex):
            assert duplex is False
            return Receiver(), Sender()

        def Process(self, **kwargs):
            return Process(**kwargs)

    monkeypatch.setattr(
        pc2_local_solver.multiprocessing, "get_context", lambda method: Context()
    )
    monkeypatch.setattr(
        pc2_solver_execution, "run_solver_local", lambda *_args, **_kwargs: True
    )

    assert (
        pc2_local_solver.run_solver_local_with_deadline(
            "http://127.0.0.1:9223",
            "https://example.test/challenge",
            timeout_seconds=12,
        )
        is True
    )
    assert process_state == {
        "name": "fapaifang-local-solver-attempt",
        "sender_closed": True,
        "join_timeout": 12.0,
        "receiver_closed": True,
        "process_closed": True,
    }


def test_run_solver_local_with_deadline_terminates_hung_child(monkeypatch) -> None:
    process_state: dict[str, object] = {"alive": True, "joins": []}
    events: list[dict[str, object]] = []

    class Connection:
        def close(self) -> None:
            process_state["connections_closed"] = (
                int(process_state.get("connections_closed", 0)) + 1
            )

    class Process:
        exitcode = None

        def start(self) -> None:
            process_state["started"] = True

        def join(self, timeout) -> None:
            process_state["joins"].append(timeout)

        def is_alive(self) -> bool:
            return bool(process_state["alive"])

        def terminate(self) -> None:
            process_state["terminated"] = True
            process_state["alive"] = False

        def kill(self) -> None:
            raise AssertionError("terminate should stop the fake process")

        def close(self) -> None:
            process_state["process_closed"] = True

    class Context:
        def Pipe(self, *, duplex):
            assert duplex is False
            return Connection(), Connection()

        def Process(self, **_kwargs):
            return Process()

    monkeypatch.setattr(
        pc2_local_solver.multiprocessing, "get_context", lambda method: Context()
    )
    monkeypatch.setattr(pc2_solver_execution, "SOLVER_TERMINATE_GRACE_SECONDS", 2.0)
    monkeypatch.setattr(
        pc2_solver_execution, "log_event", lambda event: events.append(event)
    )

    assert (
        pc2_local_solver.run_solver_local_with_deadline(
            "http://127.0.0.1:9223",
            "https://example.test/challenge",
            timeout_seconds=7,
        )
        is False
    )
    assert process_state["started"] is True
    assert process_state["terminated"] is True
    assert process_state["alive"] is False
    assert process_state["joins"] == [7.0, 2.0]
    assert process_state["process_closed"] is True
    assert events == [
        {
            "kind": "local_solver_execution_timeout",
            "timeout_seconds": 7.0,
            "terminated": True,
        }
    ]
