"""Native publication preserves callable identity and explicit dependency ownership."""

from types import ModuleType, SimpleNamespace

import pytest


@pytest.mark.parametrize("repeat", [False, True])
def test_publication_preserves_identity_metadata_aliases_and_owner_globals(repeat):
    from src.server_module_exports import ModuleExports

    owner = ModuleType("test_native_exports")
    exec(  # noqa: S102 - controlled owner fixture exercises function globals
        "base = 10\n"
        "def make_reader(offset):\n"
        "    def read(value: int = 4, *, factor: int = 2) -> int:\n"
        "        '''Read a shared base and a closed-over offset.'''\n"
        "        return base + offset + value * factor\n"
        "    return read\n"
        "read = make_reader(3)\n"
        "alias = read\n"
        "__all__ = ['read', 'alias']\n",
        vars(owner),
    )
    marker = object()
    owner.read.marker = marker
    context = ModuleType("test_export_context")
    context.__all__ = []

    def native():
        return "native"

    namespace = {"__name__": "test_facade", "base": 100, "native": native}
    exports = ModuleExports(namespace, context)
    exports.publish(owner)
    if repeat:
        exports.publish(owner)

    read = namespace["read"]
    assert read is owner.read
    assert read() == 21
    namespace["base"] = 200
    assert read(5, factor=3) == 28
    owner.base = 20
    assert read() == 31
    assert read.__globals__ is vars(owner)
    assert context.read is read
    assert read.__defaults__ is owner.read.__defaults__
    assert read.__kwdefaults__ is owner.read.__kwdefaults__
    assert read.__annotations__ is owner.read.__annotations__
    assert read.__doc__ == owner.read.__doc__
    assert read.__qualname__ == owner.read.__qualname__
    assert read.__module__ == owner.__name__
    assert read.marker is marker
    assert namespace["native"] is native
    assert namespace["alias"] is read
    assert context.alias is read
    assert context.__all__ == ["read", "alias"]


def test_status_and_cookie_exports_are_bound_native_methods():
    from src import server
    from src.auth_cookie_snapshot_jobs import AuthCookieSnapshotJobs
    from src.manual_review_readers import ManualReviewReaders
    from src.server_auth_recovery import AuthRecovery
    from src.server_collection_status import CollectionStatusReaders
    from src.server_solver_dispatch import SolverDispatch
    from src.server_solver_state import SolverState
    from src.solver_auth_history import SolverAuthHistory
    from src.solver_status_reader import SolverStatusReader

    for owner_type in (
        CollectionStatusReaders,
        AuthCookieSnapshotJobs,
        ManualReviewReaders,
        SolverDispatch,
        SolverState,
        AuthRecovery,
        SolverAuthHistory,
        SolverStatusReader,
    ):
        for name in owner_type.__all__:
            exported = getattr(server, name)
            assert isinstance(exported.__self__, owner_type)
            assert exported.__func__ is getattr(owner_type, name)
            assert getattr(server._CONTEXT, name) is exported
    for name in ("_CORE_MODULES", "_HANDLER_MODULES", "_IMPLEMENTATION_MODULES"):
        assert not hasattr(server, name)
    assert not hasattr(server._EXPORTS, "rebind")
    assert "server_handler_analysis" in server._NATIVE_MODULES


def test_retained_dispatch_uses_current_runtime_and_releases_failed_submission(
    monkeypatch,
):
    from src import server
    from src.runtime_state import RuntimeState

    submit = server._submit_solver_request
    pending = server._solver_submission_pending
    activate = server._activate_solver_submission
    request = {"target_url": "https://example.test/detail", "scope": "detail"}
    submitted = []

    class Handler:
        def run_solver(self, *_args):
            raise AssertionError("The executor must not run during this test")

    def fail_submit(*_args):
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(server, "DataHandler", Handler)
    for epoch in (101.0, 202.0):
        runtime = RuntimeState()
        monkeypatch.setattr(server, "RUNTIME", runtime)
        monkeypatch.setattr(
            server, "time", SimpleNamespace(time=lambda epoch=epoch: epoch)
        )
        monkeypatch.setattr(server, "executor", SimpleNamespace(submit=fail_submit))
        with pytest.raises(RuntimeError, match="executor unavailable"):
            submit(request)
        assert pending() is False
        monkeypatch.setattr(
            server,
            "executor",
            SimpleNamespace(submit=lambda *args: submitted.append(args)),
        )
        assert submit(request) is True
        assert pending() is True
        assert submit(request) is False
        runner, actual_request, token = submitted[-1]
        assert isinstance(runner.__self__, Handler)
        assert actual_request is request
        assert activate(request, token) == (True, "started", epoch)
        assert runtime.recovery.snapshot().last_request == request
        assert pending() is False
    assert len(submitted) == 2


def test_retained_retry_reads_current_request_and_policy_callbacks(monkeypatch):
    from src import server
    from src.runtime_state import RuntimeState

    retry = server._manual_solver_retry_request
    next_epoch = server._manual_solver_retry_next_epoch
    monkeypatch.setattr(
        server, "_prefer_seed_manual_solver_retry_request", lambda: True
    )
    monkeypatch.setattr(server, "_manual_solver_retry_enabled", lambda _scope: True)
    for interval in (10, 25):
        runtime = RuntimeState()
        runtime.recovery.set_request({"target_url": "https://example.test/detail"})
        runtime.recovery.require_manual(float(interval), manual_only=False)
        monkeypatch.setattr(server, "RUNTIME", runtime)
        monkeypatch.setattr(
            server,
            "_manual_solver_retry_interval_seconds",
            lambda interval=interval: interval,
        )
        monkeypatch.setattr(
            server,
            "_seed_priority_manual_solver_retry_request",
            lambda request, interval=interval: {
                **request,
                "target_url": f"https://example.test/seed/{interval}",
            },
        )
        assert retry()["target_url"] == f"https://example.test/seed/{interval}"
        assert next_epoch(now=1) == interval * 2


def test_retained_state_entrypoints_cancel_and_clear_current_runtime(monkeypatch):
    from src import server
    from src.runtime_state import RuntimeState

    cancel = server._request_solver_cancel
    clear = server._clear_solver_running_state
    runtimes = []
    for epoch in (111.0, 222.0):
        runtime = RuntimeState()
        execution = runtime.solver.begin(epoch - 10, resume_epoch=0, cancel_epoch=0)
        monkeypatch.setattr(server, "RUNTIME", runtime)
        monkeypatch.setattr(
            server, "time", SimpleNamespace(time=lambda epoch=epoch: epoch)
        )
        cancel()
        assert execution.cancelled.is_set()
        assert runtime.recovery.snapshot().cancel_epoch == epoch
        clear()
        assert runtime.solver.snapshot().running is False
        assert runtime.solver.snapshot().finished_at == epoch
        runtimes.append(runtime)
    assert runtimes[0].recovery.snapshot().cancel_epoch == 111.0
    assert runtimes[0].solver.snapshot().finished_at == 111.0


def test_retained_cleanup_compat_uses_current_override_without_swallowing_errors(
    monkeypatch,
):
    from src import server

    cleanup = server._clear_solver_manual_required_pause_compat
    calls = []

    def legacy():
        calls.append("legacy")
        return "legacy receipt failure"

    monkeypatch.setattr(server, "_clear_solver_manual_required_pause", legacy)
    assert cleanup("detail") == "legacy receipt failure"
    assert calls == ["legacy"]

    def scoped(*, scope):
        calls.append(scope)
        raise TypeError("persistence rejected the payload")

    monkeypatch.setattr(server, "_clear_solver_manual_required_pause", scoped)
    with pytest.raises(TypeError, match="persistence rejected"):
        cleanup("seed")
    assert calls == ["legacy", "seed"]


def test_retained_status_entrypoint_reads_replaced_runtime_and_repository(monkeypatch):
    from src import server
    from src.collection_statistics import StatisticsCache
    from src.runtime_state import RuntimeState

    read_status = server._collection_api_lightweight_status_payload
    monkeypatch.setattr(server._collection_statistics, "SNAPSHOTS", StatisticsCache())
    monkeypatch.setattr(
        server,
        "_captcha_solver_runtime_status",
        lambda: {"paused": server.RUNTIME.control.snapshot().paused},
    )
    for count, paused in ((3, False), (7, True)):
        runtime = RuntimeState()
        runtime.control.set_pause(paused, "operator")
        monkeypatch.setattr(server, "RUNTIME", runtime)
        monkeypatch.setattr(
            server,
            "DB_REPOSITORY",
            SimpleNamespace(
                enabled=True,
                seed_queue_counts=lambda count=count: {
                    "seed_item_raw_detail_captured": count
                },
            ),
        )
        monkeypatch.setattr(
            server,
            "NAS_AUTH_RECOVERY",
            SimpleNamespace(snapshot=lambda count=count: {"receipt": count}),
        )
        monkeypatch.setattr(
            server,
            "llm_helper",
            SimpleNamespace(get_api_metrics=lambda count=count: {"total_calls": count}),
        )
        status = read_status()
        assert status["paused"] is paused
        assert status["captured_count"] == count
        assert status["auth_recovery"] == {"receipt": count}
        assert status["api_total_calls"] == count
        assert status["statistics"]["valid"] is True
