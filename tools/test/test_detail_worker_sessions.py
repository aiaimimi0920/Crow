"""Worker-owned HTTP sessions close; borrowed sessions keep their owner."""

import importlib
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tools import detail_worker as worker
from tools import worker_lifecycle


def session():
    value = SimpleNamespace(close_calls=0)

    def close():
        value.close_calls += 1

    value.close = close
    return value


@pytest.fixture(params=["tools.detail_worker", "tools.detail_worker_loop"])
def loop(request, monkeypatch, tmp_path):
    module = importlib.import_module(request.param)
    monkeypatch.setattr(
        module, "_write_runtime_summary", lambda *_: None, raising=False
    )
    monkeypatch.setattr(
        module, "_detail_batch_progress_event", lambda *_: {}, raising=False
    )
    monkeypatch.setattr(worker_lifecycle, "checkpoint", lambda _: True)
    monkeypatch.setattr(worker_lifecycle, "wait", lambda _: None)
    config = module.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="",
        target_success=1,
        max_attempts=1,
        worker_id="session-owner-test",
        do_risk=False,
        max_runs=2,
        loop_interval_seconds=0,
    )

    def run(contexts, batch=None, **options):
        remaining = iter(contexts)

        def build(_config):
            value = next(remaining)
            if isinstance(value, BaseException):
                raise value
            return value, {}

        def default_batch(*_args, http_session, **_kwargs):
            assert http_session.close_calls == 0
            return {"decision": "detail_worker_batch_finished"}

        monkeypatch.setattr(module, "_build_runtime_context", build, raising=False)
        monkeypatch.setattr(module, "run_detail_worker_batch", batch or default_batch)
        return module.run_detail_worker_loop(
            config,
            repository=SimpleNamespace(seed_queue_counts=dict),
            progress_emit_func=lambda _: None,
            **options,
        )

    return SimpleNamespace(run=run, module=module, config=config)


def test_replacement_closes_previous_session_only_after_refresh_succeeds(loop):
    first, second = session(), session()
    observed = []

    def batch(*_args, http_session, **_kwargs):
        observed.append((http_session, first.close_calls, second.close_calls))
        return {"decision": "detail_worker_batch_finished"}

    loop.run([first, second], batch)
    assert observed == [(first, 0, 0), (second, 1, 0)]
    assert (first.close_calls, second.close_calls) == (1, 1)


def test_failed_refresh_keeps_previous_session_usable_until_exit(loop):
    owned = session()
    result = loop.run([owned, OSError("synthetic refresh failure")])
    assert result["runs"] == 2
    assert owned.close_calls == 1


def test_same_owned_session_is_not_closed_between_batches(loop):
    owned = session()
    loop.run([owned, owned])
    assert owned.close_calls == 1


def test_close_failure_does_not_discard_replacement_or_expose_error_body(loop, caplog):
    first, second = session(), session()

    def fail_close():
        first.close_calls += 1
        raise OSError("synthetic-private-close-detail")

    first.close = fail_close
    result = loop.run([first, second])
    assert result["runs"] == 2
    assert (first.close_calls, second.close_calls) == (1, 1)
    assert "detail_worker_http_session_close_failed" in caplog.text
    assert "synthetic-private-close-detail" not in caplog.text


def test_cleanup_error_does_not_replace_the_original_batch_error(loop):
    owned = session()
    original = ValueError("synthetic original batch failure")

    def fail_close():
        owned.close_calls += 1
        raise OSError("synthetic close failure")

    def fail_batch(*_args, **_kwargs):
        raise original

    owned.close = fail_close
    with pytest.raises(ValueError) as raised:
        loop.run([owned], fail_batch)
    assert raised.value is original
    assert owned.close_calls == 1


@pytest.mark.parametrize("error_type", [RuntimeError, BaseException])
def test_batch_exception_preserved_after_owned_session_cleanup(loop, error_type):
    owned = session()
    original = error_type("synthetic batch failure")

    def fail(*_args, **_kwargs):
        raise original

    with pytest.raises(error_type) as raised:
        loop.run([owned], fail)
    assert raised.value is original
    assert owned.close_calls == 1


def test_loop_stop_releases_last_owned_session(loop, monkeypatch):
    owned = session()
    cycles = []

    def checkpoint(stage):
        if stage == "detail_cycle":
            cycles.append(stage)
        return len(cycles) <= 1

    monkeypatch.setattr(worker_lifecycle, "checkpoint", checkpoint)
    loop.run([owned])
    assert owned.close_calls == 1


@pytest.mark.parametrize("factory", [False, True])
def test_externally_supplied_context_remains_borrowed(loop, factory):
    borrowed = session()
    options = (
        {"runtime_context_factory": lambda: (borrowed, {})}
        if factory
        else {"http_session": borrowed, "browser_pages": {}}
    )
    loop.run([], **options)
    assert borrowed.close_calls == 0


@pytest.mark.parametrize("continuous", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_cli_closes_owned_sessions_in_batch_and_loop(
    monkeypatch, tmp_path, continuous, failed
):
    from tools import worker_lifecycle as lifecycle

    first, second = session(), session()
    contexts = iter([(first, {}), (second, {})])
    config = worker.DetailWorkerConfig(tmp_path, "", 1, 1, "cli-session-test", False)
    monkeypatch.setattr(
        worker, "config_from_env_and_args", lambda _: (config, continuous)
    )
    repository = SimpleNamespace(
        enabled=True, release_seed_detail_worker_leases=lambda _: None
    )
    monkeypatch.setattr(worker, "create_repository_from_env", lambda: repository)
    monkeypatch.setattr(lifecycle, "WorkerLifecycle", lambda *_: nullcontext())
    monkeypatch.setattr(worker, "_build_runtime_context", lambda _: next(contexts))

    def run(*_args, **options):
        if continuous:
            assert options["runtime_context_factory"]() == (first, {})
            assert first.close_calls == 0
            assert options["runtime_context_factory"]() == (second, {})
        else:
            assert options["http_session"] is first
        if failed:
            raise ValueError("synthetic CLI failure")
        return {"decision": "finished"}

    monkeypatch.setattr(worker, "run_detail_worker_loop", run)
    monkeypatch.setattr(worker, "run_detail_worker_batch", run)
    if failed:
        with pytest.raises(ValueError, match="synthetic CLI failure"):
            worker.main([])
    else:
        assert worker.main([]) == 0
    assert first.close_calls == 1
    assert second.close_calls == int(continuous)


@pytest.mark.parametrize("continuous", [False, True])
def test_analysis_cli_never_builds_a_collection_http_context(
    monkeypatch, tmp_path, continuous
):
    config = worker.DetailWorkerConfig(
        tmp_path, "", 1, 1, "analysis-session-test", False
    )
    config = replace(config, analysis_only=True)
    monkeypatch.setattr(
        worker, "config_from_env_and_args", lambda _: (config, continuous)
    )
    repository = SimpleNamespace(
        enabled=True, release_seed_detail_worker_leases=lambda _: None
    )
    monkeypatch.setattr(worker, "create_repository_from_env", lambda: repository)
    monkeypatch.setattr(worker_lifecycle, "WorkerLifecycle", lambda *_: nullcontext())
    monkeypatch.setattr(
        worker, "_build_runtime_context", lambda _: pytest.fail("collection context")
    )

    def run(*_args, **options):
        context = (
            options["runtime_context_factory"]()
            if continuous
            else (options["http_session"], options["browser_pages"])
        )
        assert context == (None, {})
        return {"decision": "finished"}

    monkeypatch.setattr(worker, "run_detail_worker_loop", run)
    monkeypatch.setattr(worker, "run_detail_worker_batch", run)
    assert worker.main([]) == 0
