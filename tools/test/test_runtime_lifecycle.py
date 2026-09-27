"""Runtime startup owns its clock and only starts active background workers."""

from types import SimpleNamespace

import pytest

from src.runtime_state import RuntimeState


@pytest.fixture
def startup(monkeypatch):
    from src import server

    runtime = RuntimeState()
    targets = []

    class FakeThread:
        def __init__(self, *, target, daemon):
            assert daemon is True
            self.target = target

        def start(self):
            targets.append(self.target)

    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "threading", SimpleNamespace(Thread=FakeThread))
    for name in (
        "_restore_solver_challenge_state",
        "_restore_solver_scope_states",
        "cleanup_orphaned_files",
        "load_data",
        "_sample_nas_auth_recovery",
    ):
        monkeypatch.setattr(server, name, lambda: None)
    monkeypatch.setattr(
        server, "DB_REPOSITORY", SimpleNamespace(enabled=False, initialize=lambda: None)
    )
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", SimpleNamespace(enabled=False))
    monkeypatch.setattr(server, "_manual_solver_retry_interval_seconds", lambda: 1)
    monkeypatch.setattr(server, "_manual_solver_retry_poll_seconds", lambda: 1)
    return SimpleNamespace(server=server, runtime=runtime, targets=targets)


def test_health_clock_reads_runtime_state_without_overwriting_it(startup):
    startup.runtime.started_at = 123.0

    assert startup.server._runtime_started_at() == 123.0
    assert startup.runtime.started_at == 123.0
    assert startup.runtime.initialized is False


@pytest.mark.parametrize("recovery_enabled", [False, True])
def test_startup_only_starts_active_background_workers(
    startup, monkeypatch, recovery_enabled
):
    server = startup.server
    monkeypatch.setattr(
        server,
        "NAS_AUTH_RECOVERY",
        SimpleNamespace(enabled=recovery_enabled, stall_seconds=60),
    )

    server.initialize_runtime()
    server.initialize_runtime()

    expected = [server.manual_solver_retry_thread]
    if recovery_enabled:
        expected.append(server.nas_auth_recovery_watchdog_thread)
    assert startup.targets == expected
    assert startup.runtime.initialized is True


def test_saved_native_startup_follows_runtime_and_clock_replacement(
    startup, monkeypatch
):
    from src import server_data_runtime
    from src.collection_startup import CollectionStartup

    initialize = startup.server.initialize_runtime
    assert isinstance(initialize.__self__, CollectionStartup)
    assert startup.server._CONTEXT.initialize_runtime is initialize
    assert isinstance(
        server_data_runtime.initialize_runtime.__self__, CollectionStartup
    )
    replacement = RuntimeState()
    monkeypatch.setattr(startup.server, "RUNTIME", replacement)
    monkeypatch.setattr(startup.server, "time", SimpleNamespace(time=lambda: 321.0))
    initialize()
    initialize()
    assert replacement.initialized is True
    assert replacement.started_at == 321.0
    assert startup.runtime.initialized is False
    assert startup.targets == [startup.server.manual_solver_retry_thread]


@pytest.mark.parametrize("failure_stage", ["database", "seed", "sample"])
def test_optional_startup_failure_preserves_order_and_starts_workers(
    startup, monkeypatch, caplog, failure_stage
):
    server = startup.server
    events = []

    def stage(name):
        def run():
            events.append(name)
            if name == failure_stage:
                raise OSError("isolated optional startup failure")

        return run

    monkeypatch.setattr(server, "cleanup_orphaned_files", stage("cleanup"))
    monkeypatch.setattr(server, "load_data", stage("load"))
    monkeypatch.setattr(
        server,
        "DB_REPOSITORY",
        SimpleNamespace(enabled=True, initialize=stage("database")),
    )
    monkeypatch.setattr(
        server,
        "_seed_collection_service",
        lambda: SimpleNamespace(_bootstrap_db_search_tasks=stage("seed")),
    )
    monkeypatch.setattr(server, "_sample_nas_auth_recovery", stage("sample"))
    server.initialize_runtime()
    assert events == (
        ["cleanup", "load", "database", "sample"]
        if failure_stage == "database"
        else ["cleanup", "load", "database", "seed", "sample"]
    )
    assert startup.targets == [server.manual_solver_retry_thread]
    assert startup.runtime.initialized is True
    assert "isolated optional startup failure" in caplog.text


def test_failed_data_load_can_retry_without_leaking_background_workers(
    startup, monkeypatch
):
    attempts = []
    started_at = startup.runtime.started_at

    def load_data():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("isolated startup failure")

    monkeypatch.setattr(startup.server, "load_data", load_data)
    with pytest.raises(OSError, match="isolated startup failure"):
        startup.server.initialize_runtime()

    assert startup.targets == []
    assert startup.runtime.initialized is False
    assert startup.runtime.started_at == started_at
    startup.server.initialize_runtime()
    startup.server.initialize_runtime()
    assert len(attempts) == 2
    assert startup.targets == [startup.server.manual_solver_retry_thread]
    assert startup.runtime.initialized is True
