"""Compose dispatch callbacks against a live server facade without cloning globals."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Executor
from contextlib import AbstractContextManager
from threading import Event
from typing import BinaryIO, Protocol

from .runtime_state import RuntimeState
from .server_solver_dispatch import SolverDispatch


class SolverHandler(Protocol):
    def run_solver(self, request: dict[str, object], token: object) -> object: ...


class DispatchClock(Protocol):
    time: Callable[[], float]
    monotonic: Callable[[], float]


class DispatchThreading(Protocol):
    Event: Callable[[], Event]


class SolverDispatchHost(Protocol):
    RUNTIME: RuntimeState
    time: DispatchClock
    threading: DispatchThreading
    executor: Executor
    DataHandler: type[SolverHandler]
    urlopen: Callable[..., AbstractContextManager[BinaryIO]]
    _normalize_challenge_scope: Callable[[object], str | None]
    _solver_scope_manual_flag_path: Callable[[str], str]
    _solver_force_unlock_flag_path: Callable[[], str]
    _challenge_scope_for_request: Callable[[dict[str, str]], str | None]
    _solver_scope_runtime_status: Callable[[str], Mapping[str, object]]
    _solver_manual_flag_scope: Callable[[], str | None]
    _solver_manual_flag_is_manual_only: Callable[[], bool]
    _runtime_env_flag: Callable[[str, bool], bool]
    _solver_cdp_ready_timeout_seconds: Callable[[], int]
    _solver_cdp_probe_timeout_seconds: Callable[[], float]
    _captcha_solver_background_url: Callable[[str], str]
    _auth_cookie_snapshot_sample_urls: Callable[[dict[str, object]], Sequence[str]]
    _collection_api_lightweight_status_payload: Callable[[], object]
    _solver_last_request_scope: Callable[[], str]
    _seed_stage_has_remaining_work: Callable[[object], bool]
    _build_solver_request: Callable[[object], dict[str, object]]
    _default_manual_solver_retry_request: Callable[[], dict[str, object]]
    _solver_request_scope: Callable[[object], str]
    _prefer_seed_solver_request_for_payload: Callable[[object], bool]
    _seed_priority_manual_solver_retry_request: Callable[[object], dict[str, object]]
    _prefer_seed_manual_solver_retry_request: Callable[[], bool]
    _solver_manual_flag_request: Callable[[], dict[str, object]]
    _manual_solver_retry_enabled: Callable[[str | None], bool]
    _manual_solver_retry_interval_seconds: Callable[[], int]
    _solver_cdp_endpoint_is_remote: Callable[[str], bool]
    _reserve_solver_submission: Callable[[], object | None]
    _release_solver_submission: Callable[[object | None], None]


def bind_solver_dispatch(host: SolverDispatchHost) -> SolverDispatch:
    return SolverDispatch(
        runtime=lambda: host.RUNTIME,
        clock=lambda: host.time.time(),
        monotonic=lambda: host.time.monotonic(),
        event=lambda: host.threading.Event(),
        open_url=lambda *args, **kwargs: host.urlopen(*args, **kwargs),
        runner=lambda: object.__new__(host.DataHandler).run_solver,
        submit=lambda *args: host.executor.submit(*args),
        normalize_scope=lambda scope: host._normalize_challenge_scope(scope),
        scope_flag_path=lambda scope: host._solver_scope_manual_flag_path(scope),
        flag_path=lambda: host._solver_force_unlock_flag_path(),
        infer_scope=lambda request: host._challenge_scope_for_request(request),
        scope_status=lambda scope: host._solver_scope_runtime_status(scope),
        flag_scope=lambda: host._solver_manual_flag_scope(),
        flag_manual_only=lambda: host._solver_manual_flag_is_manual_only(),
        env_flag=lambda name, default: host._runtime_env_flag(name, default),
        ready_timeout=lambda: host._solver_cdp_ready_timeout_seconds(),
        probe_timeout=lambda: host._solver_cdp_probe_timeout_seconds(),
        background_url=lambda url: host._captcha_solver_background_url(url),
        sample_urls=lambda request: host._auth_cookie_snapshot_sample_urls(request),
        status=lambda: host._collection_api_lightweight_status_payload(),
        last_scope=lambda: host._solver_last_request_scope(),
        seed_pending=lambda status: host._seed_stage_has_remaining_work(status),
        build_request=lambda request: host._build_solver_request(request),
        default_request=lambda: host._default_manual_solver_retry_request(),
        request_scope=lambda request: host._solver_request_scope(request),
        prefer_seed_payload=lambda request: (
            host._prefer_seed_solver_request_for_payload(request)
        ),
        seed_priority_request=lambda request: (
            host._seed_priority_manual_solver_retry_request(request)
        ),
        prefer_seed_retry=lambda: host._prefer_seed_manual_solver_retry_request(),
        flag_request=lambda: host._solver_manual_flag_request(),
        retry_enabled=lambda scope: host._manual_solver_retry_enabled(scope),
        retry_interval=lambda: host._manual_solver_retry_interval_seconds(),
        remote_endpoint=lambda endpoint: host._solver_cdp_endpoint_is_remote(endpoint),
        reserve=lambda: host._reserve_solver_submission(),
        release=lambda token: host._release_solver_submission(token),
    )
