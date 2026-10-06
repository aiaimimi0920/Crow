"""Compose cookie paths, refresh state and challenge report dependencies."""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from .auth_cookie_paths import AuthCookiePaths, EnvironmentReader
from .auth_cookie_snapshot_state import AuthCookieSnapshotState
from .runtime_state import RuntimeState
from .server_auth_cookie import AuthCookieSnapshot, CookieExporter, CookieHealthProbe
from .solver_captcha_reports import PayloadFlag, ReportMarker, SolverCaptchaReports
from .solver_pause_cleanup import PauseSetter


class CookieEnvironment(Protocol):
    getenv: EnvironmentReader


class CookieClock(Protocol):
    time: Callable[[], float]


class AuthCookieHost(Protocol):
    RUNTIME: RuntimeState
    REPO_ROOT: Path
    DATA_DIR: str
    os: CookieEnvironment
    time: CookieClock
    _payload_flag: PayloadFlag
    _build_solver_request: Callable[[object], dict[str, str]]
    _refresh_solver_last_request: Callable[[dict[str, str]], object]
    _challenge_scope_for_request: Callable[[object], str | None]
    _begin_solver_challenge: Callable[[object], str]
    _mark_solver_manual_required: ReportMarker
    _captcha_solver_runtime_status: Callable[[], dict[str, object]]
    _read_solver_scope_state: Callable[[str], dict[str, object]]
    _persist_solver_scope_state: Callable[[str, dict[str, object]], str | None]
    _set_collection_pause_state: PauseSetter
    _normalize_auth_cookie_snapshot_node_id: Callable[[object], str]
    _auth_cookie_snapshot_root_candidates: Callable[[], list[Path]]
    _resolve_auth_cookie_snapshot_path: Callable[[dict[str, object]], str]
    _normalize_solver_cdp_endpoint: Callable[[object], str]
    _cdp_endpoint_permitted: Callable[[str], bool]
    _export_auth_cdp_cookies: CookieExporter
    _summarize_auth_cookies: Callable[[list[dict[str, object]]], Mapping[str, object]]
    _auth_cookie_snapshot_sample_urls: Callable[[dict[str, object]], list[str]]
    _probe_auth_cookie_snapshot_health: CookieHealthProbe
    _write_auth_cookie_snapshot: Callable[[list[dict[str, object]], str], None]
    _auth_cookie_snapshot_runtime_state: Callable[[], AuthCookieSnapshotState]


def bind_auth_cookie(
    host: AuthCookieHost,
) -> tuple[SolverCaptchaReports, AuthCookiePaths, AuthCookieSnapshot]:
    reports = SolverCaptchaReports(
        flag=lambda payload, key, default: host._payload_flag(payload, key, default),
        build_request=lambda payload: host._build_solver_request(payload),
        refresh_request=lambda request: host._refresh_solver_last_request(request),
        infer_scope=lambda request: host._challenge_scope_for_request(request),
        begin=lambda request: host._begin_solver_challenge(request),
        mark_manual=lambda **kwargs: host._mark_solver_manual_required(**kwargs),
        status=lambda: host._captcha_solver_runtime_status(),
        read_scope=lambda scope: host._read_solver_scope_state(scope),
        clock=lambda: host.time.time(),
        persist=lambda scope, state: host._persist_solver_scope_state(scope, state),
        set_pause=lambda paused, reason=None, **kwargs: (
            host._set_collection_pause_state(paused, reason, **kwargs)
        ),
    )
    paths = AuthCookiePaths(
        env=lambda name, default=None: host.os.getenv(name, default),
        repo_root=lambda: host.REPO_ROOT,
        data_dir=lambda: host.DATA_DIR,
        normalize_node=lambda value: host._normalize_auth_cookie_snapshot_node_id(
            value
        ),
        roots=lambda: host._auth_cookie_snapshot_root_candidates(),
    )
    snapshot = AuthCookieSnapshot(
        runtime=lambda: host.RUNTIME,
        env=lambda name, default=None: host.os.getenv(name, default),
        flag=lambda payload, key, default: host._payload_flag(payload, key, default),
        resolve_path=lambda payload: host._resolve_auth_cookie_snapshot_path(payload),
        normalize_endpoint=lambda endpoint: host._normalize_solver_cdp_endpoint(
            endpoint
        ),
        permitted=lambda endpoint: host._cdp_endpoint_permitted(endpoint),
        export=lambda endpoint, **kwargs: host._export_auth_cdp_cookies(
            endpoint, **kwargs
        ),
        summarize=lambda cookies: host._summarize_auth_cookies(cookies),
        sample_urls=lambda payload: host._auth_cookie_snapshot_sample_urls(payload),
        health=lambda cookies, sample_urls, **kwargs: (
            host._probe_auth_cookie_snapshot_health(cookies, sample_urls, **kwargs)
        ),
        write=lambda cookies, path: host._write_auth_cookie_snapshot(cookies, path),
        state=lambda: host._auth_cookie_snapshot_runtime_state(),
        read_scope=lambda scope: host._read_solver_scope_state(scope),
    )
    return reports, paths, snapshot
