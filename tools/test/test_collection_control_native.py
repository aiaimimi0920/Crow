"""Native observer/control exports retain live resources and fail-closed resume."""

from types import SimpleNamespace

import pytest

from src.runtime_state import RuntimeState
from src.server_collection_control import CollectionObserver, CollectionRuntimeControl


def test_control_exports_are_native_and_share_context_identity():
    from src import server

    assert not hasattr(server, "_CORE_MODULES")
    for owner in (CollectionObserver, CollectionRuntimeControl):
        for name in owner.__all__:
            method = getattr(server, name)
            assert isinstance(method.__self__, owner)
            assert getattr(server._CONTEXT, name) is method


def test_saved_observer_query_reads_replaced_repository(monkeypatch):
    from src import server

    query = server._collection_observer_items_payload
    for marker in ("old", "replacement"):
        repository = SimpleNamespace(
            enabled=True,
            collection_observer_items=lambda value=marker, **kwargs: {"marker": value},
        )
        monkeypatch.setattr(server, "DB_REPOSITORY", repository)
        assert query({})["marker"] == marker


@pytest.mark.parametrize("paused, expected", [(True, "暂停中"), (False, "运行中")])
def test_saved_runtime_label_falls_back_when_status_fails(
    monkeypatch, paused, expected
):
    from src import server

    label = server._collection_runtime_state_label
    monkeypatch.setattr(server, "_collection_effectively_paused", lambda: paused)
    monkeypatch.setattr(
        server,
        "_collection_api_lightweight_status_payload",
        lambda: {"runtime_state": " custom "},
    )
    assert label() == "custom"

    def unavailable():
        raise RuntimeError("status unavailable")

    monkeypatch.setattr(
        server, "_collection_api_lightweight_status_payload", unavailable
    )
    assert label() == expected


def test_saved_control_uses_replaced_filesystem_runtime_and_clock(monkeypatch):
    from src import server

    control = server._collection_observer_runtime_control_payload
    runtime = RuntimeState()
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: "flag")
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", dict)
    monkeypatch.setattr(server, "_collection_runtime_state_label", lambda: "test")
    monkeypatch.setattr(server, "_clear_solver_running_state", lambda: None)
    monkeypatch.setattr(server, "_clear_solver_manual_required_state", lambda: None)
    cleared = []
    monkeypatch.setattr(
        server, "_clear_solver_challenge_state", lambda: cleared.append(True)
    )

    def locked(_):
        raise PermissionError("flag locked")

    monkeypatch.setattr(
        server,
        "os",
        SimpleNamespace(path=SimpleNamespace(exists=lambda _: True), remove=locked),
    )
    failed = control("resume")
    assert failed["ok"] is False
    assert failed["paused"] is True
    assert cleared == []
    assert runtime.recovery.snapshot().resume_epoch == 0

    replacement = RuntimeState()
    replacement.control.set_pause(True, "operator")
    monkeypatch.setattr(server, "RUNTIME", replacement)
    monkeypatch.setattr(
        server, "os", SimpleNamespace(path=SimpleNamespace(exists=lambda _: False))
    )
    monkeypatch.setattr(server, "time", SimpleNamespace(time=lambda: 123.0))
    assert control("resume")["ok"] is True
    assert replacement.recovery.snapshot().resume_epoch == 123.0
    assert replacement.control.snapshot().paused is False
    assert runtime.control.snapshot().paused is True
