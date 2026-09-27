from tools import pc2_solver_cdp
from tools.test.pc2_local_solver_test_context import *
from tools.test.pc2_loop_test_dependencies import patch_loop_dependency


def test_paused_api_trigger_falls_back_to_active_seed_request_route(
    monkeypatch,
) -> None:
    detail_target_url = "https://detail.example.test/item"
    seed_target_url = "https://seed.example.test/list"
    challenge_target = {
        "_target_id": "seed-punish-target",
        "_target_url": seed_target_url + "/_____tmd_____/punish",
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/seed-punish-target",
    }
    slider_probes: list[str | None] = []
    challenge_probes: list[str | None] = []
    solver_calls: list[dict[str, object]] = []
    state = pc2_local_solver._default_fallback_state()

    solver_status = {
        "paused": True,
        "running": False,
        "manual_required": False,
        "challenge_id": "challenge-mixed-route",
        "last_request": {
            "target_url": seed_target_url,
            "challenge_target_url": detail_target_url,
            "cdp_endpoint": pc2_local_solver.DEFAULT_CDP_ENDPOINT,
        },
    }
    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch, "_retry_pending_auth_confirmation", lambda _api: {}
    )
    patch_loop_dependency(
        monkeypatch, "_retry_pending_collection_resume", lambda _api: {}
    )
    patch_loop_dependency(monkeypatch, "read_solver_status", lambda _api: solver_status)
    patch_loop_dependency(monkeypatch, "_load_fallback_state", lambda: dict(state))
    patch_loop_dependency(monkeypatch, "_save_fallback_state", lambda _state: None)
    patch_loop_dependency(
        monkeypatch,
        "_sync_challenge_state",
        lambda value, _challenge, scope=None: (value, False),
    )

    def unexpected_sleep(_seconds):
        raise AssertionError("owned challenge must reach the solver without waiting")

    monkeypatch.setattr(pc2_local_solver.time, "sleep", unexpected_sleep)

    def fake_slider_probe(_endpoint, *, target_url=None):
        slider_probes.append(target_url)

    def fake_challenge_probe(_endpoint, *, target_url=None):
        challenge_probes.append(target_url)
        return challenge_target if target_url == seed_target_url else None

    patch_loop_dependency(
        monkeypatch, "check_cdp_browser_for_slider", fake_slider_probe
    )
    patch_loop_dependency(
        monkeypatch, "check_cdp_browser_for_challenge_page", fake_challenge_probe
    )

    def fake_run_solver(_endpoint, target_url, **kwargs) -> bool:
        solver_calls.append({"target_url": target_url, **kwargs})
        raise SystemExit

    patch_loop_dependency(
        monkeypatch, "run_solver_local_with_deadline", fake_run_solver
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert slider_probes == [detail_target_url, seed_target_url]
    assert challenge_probes == [detail_target_url, seed_target_url]
    assert solver_calls == [
        {
            "target_url": seed_target_url,
            "max_attempts": pc2_local_solver.DEFAULT_MAX_ATTEMPTS,
            "probe_target": challenge_target,
            "drag_profile_offset": 0,
        }
    ]


def test_paused_api_trigger_passes_existing_hard_block_target(monkeypatch) -> None:
    challenge_target = {
        "_target_id": "punish-target",
        "_target_url": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5step=1",
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/punish-target",
    }
    captured: list[dict[str, object] | None] = []
    state = pc2_local_solver._default_fallback_state()

    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch, "_retry_pending_auth_confirmation", lambda _api: {}
    )
    patch_loop_dependency(
        monkeypatch, "_retry_pending_collection_resume", lambda _api: {}
    )
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "challenge_id": "challenge-1",
            "last_request": {
                "target_url": "https://example.test/requested-page-14",
                "cdp_endpoint": pc2_local_solver.DEFAULT_CDP_ENDPOINT,
            },
        },
    )
    patch_loop_dependency(monkeypatch, "_load_fallback_state", lambda: dict(state))
    patch_loop_dependency(monkeypatch, "_save_fallback_state", lambda _state: None)
    patch_loop_dependency(
        monkeypatch,
        "_sync_challenge_state",
        lambda value, _challenge, scope=None: (value, False),
    )

    def unexpected_sleep(_seconds):
        raise AssertionError("owned challenge must reach the solver without waiting")

    monkeypatch.setattr(pc2_local_solver.time, "sleep", unexpected_sleep)
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_slider",
        lambda _endpoint, **_kwargs: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_challenge_page",
        lambda _endpoint, **_kwargs: challenge_target,
    )

    def fake_run_solver(*_args, **kwargs) -> bool:
        captured.append(kwargs.get("probe_target"))
        raise SystemExit

    patch_loop_dependency(
        monkeypatch, "run_solver_local_with_deadline", fake_run_solver
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert captured == [challenge_target]


def test_paused_api_without_current_cdp_challenge_does_not_run_solver(
    monkeypatch,
) -> None:
    state = pc2_local_solver._default_fallback_state()

    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch, "_retry_pending_auth_confirmation", lambda _api, **_kwargs: {}
    )
    patch_loop_dependency(
        monkeypatch, "_retry_pending_collection_resume", lambda _api, **_kwargs: {}
    )
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "challenge_id": "challenge-1",
            "last_status": "failed",
            "last_request": {"target_url": "https://example.test/requested-page"},
        },
    )
    patch_loop_dependency(monkeypatch, "_load_fallback_state", lambda: dict(state))
    patch_loop_dependency(monkeypatch, "_save_fallback_state", lambda _state: None)
    patch_loop_dependency(
        monkeypatch,
        "_sync_challenge_state",
        lambda value, _challenge, scope=None: (value, False),
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_slider",
        lambda _endpoint, **_kwargs: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_challenge_page",
        lambda _endpoint, **_kwargs: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "run_solver_local_with_deadline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("solver must not run without CDP evidence")
        ),
    )
    monkeypatch.setattr(
        pc2_local_solver.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(SystemExit()),
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)


def test_paused_owned_challenge_rebuilds_missing_cdp_target(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    rebuilt: list[tuple[str, str]] = []
    events: list[dict[str, object]] = []

    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)
    patch_loop_dependency(
        monkeypatch, "_retry_pending_auth_confirmation", lambda _api, **_kwargs: {}
    )
    patch_loop_dependency(
        monkeypatch, "_retry_pending_collection_resume", lambda _api, **_kwargs: {}
    )
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "challenge_id": "challenge-detail",
            "last_status": "failed",
            "last_request": {
                "node_id": "pc2",
                "cdp_endpoint": "http://127.0.0.1:9223",
                "target_url": "https://sf-item.taobao.com/sf_item/747890132583.htm",
            },
        },
    )
    patch_loop_dependency(
        monkeypatch, "compact_active_challenge_pages", lambda *_args: {}
    )
    patch_loop_dependency(monkeypatch, "_load_fallback_state", lambda: dict(state))
    patch_loop_dependency(monkeypatch, "_save_fallback_state", lambda _state: None)
    patch_loop_dependency(
        monkeypatch,
        "_sync_challenge_state",
        lambda value, _challenge, scope=None: (value, False),
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_slider",
        lambda _endpoint, **_kwargs: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_challenge_page",
        lambda _endpoint, **_kwargs: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_authenticated_target",
        lambda _endpoint, _target_url: None,
    )

    def fake_rebuild(endpoint, target_url):
        rebuilt.append((endpoint, target_url))
        return {
            "attempted": True,
            "opened": True,
            "scope": "detail",
            "reason": "missing_challenge_target_rebuilt",
            "probe_target": {"_target_id": "detail-rebuilt"},
        }

    patch_loop_dependency(monkeypatch, "rebuild_missing_challenge_target", fake_rebuild)
    patch_loop_dependency(
        monkeypatch, "log_event", lambda event: events.append(dict(event))
    )
    patch_loop_dependency(
        monkeypatch,
        "run_solver_local_with_deadline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("solver must wait for fresh CDP challenge evidence")
        ),
    )
    monkeypatch.setattr(
        pc2_local_solver.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(SystemExit()),
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(
            cdp_endpoint="http://127.0.0.1:9223",
            poll_seconds=1,
            expected_node_id="pc2",
        )

    assert rebuilt == [
        (
            "http://127.0.0.1:9223",
            "https://sf-item.taobao.com/sf_item/747890132583.htm",
        )
    ]
    assert any(
        event.get("kind") == "missing_challenge_target_rebuild_result"
        and event.get("opened") is True
        for event in events
    )


def test_stale_api_pause_after_recent_healthy_auth_is_reconfirmed(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    state["challenge_id"] = "challenge-late-report"
    pending_states: list[dict[str, object]] = []

    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)

    def fake_retry_auth(_api, state=None, **_kwargs):
        if state is None:
            return {}
        pending_states.append(state)
        return {"confirmed": True, "pending": False}

    patch_loop_dependency(
        monkeypatch, "_retry_pending_auth_confirmation", fake_retry_auth
    )
    patch_loop_dependency(
        monkeypatch, "_retry_pending_collection_resume", lambda _api, **_kwargs: {}
    )
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "force_unlock_flag_exists": False,
            "challenge_id": "challenge-late-report",
            "last_status": "manual_auth_completed",
            "last_request": {"target_url": "https://example.test/requested-page"},
            "cookie_snapshot_refresh": {
                "status": "completed",
                "refreshed": True,
                "last_finished_at_epoch": 1000.0,
                "result": {"health": {"healthy": True}},
            },
        },
    )
    patch_loop_dependency(monkeypatch, "_load_fallback_state", lambda: dict(state))
    patch_loop_dependency(monkeypatch, "_save_fallback_state", lambda _state: None)
    patch_loop_dependency(
        monkeypatch,
        "_sync_challenge_state",
        lambda value, _challenge, scope=None: (value, False),
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_slider",
        lambda _endpoint, **_kwargs: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_challenge_page",
        lambda _endpoint, **_kwargs: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_authenticated_target",
        lambda _endpoint, _target_url: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "_mark_auth_complete_pending",
        lambda target_url, challenge_id=None: {
            **state,
            "auth_complete_pending": True,
            "target_url": target_url,
            "challenge_id": challenge_id,
        },
    )
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1100.0)
    monkeypatch.setattr(
        pc2_local_solver.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(SystemExit()),
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert len(pending_states) == 1
    assert pending_states[0]["challenge_id"] == "challenge-late-report"
    assert pending_states[0]["target_url"] == "https://example.test/requested-page"


def test_existing_authenticated_target_reconfirms_pause_without_cookie_snapshot(
    monkeypatch,
) -> None:
    state = pc2_local_solver._default_fallback_state()
    pending_states: list[dict[str, object]] = []
    marked: list[tuple[str, str | None]] = []

    patch_loop_dependency(monkeypatch, "check_cdp_healthy", lambda _endpoint: True)

    def fake_retry_auth(_api, state=None, **_kwargs):
        if state is None:
            return {}
        pending_states.append(state)
        return {"confirmed": True, "pending": False}

    patch_loop_dependency(
        monkeypatch, "_retry_pending_auth_confirmation", fake_retry_auth
    )
    patch_loop_dependency(
        monkeypatch, "_retry_pending_collection_resume", lambda _api, **_kwargs: {}
    )
    patch_loop_dependency(
        monkeypatch,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "force_unlock_flag_exists": False,
            "challenge_id": "challenge-healthy-page",
            "last_status": "manual_auth_completed",
            "last_request": {"target_url": "https://example.test/requested-page"},
            "cookie_snapshot_refresh": {"status": "skipped", "refreshed": False},
        },
    )
    patch_loop_dependency(monkeypatch, "_load_fallback_state", lambda: dict(state))
    patch_loop_dependency(monkeypatch, "_save_fallback_state", lambda _state: None)
    patch_loop_dependency(
        monkeypatch,
        "_sync_challenge_state",
        lambda value, _challenge, scope=None: (value, False),
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_slider",
        lambda _endpoint, **_kwargs: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_challenge_page",
        lambda _endpoint, **_kwargs: None,
    )
    patch_loop_dependency(
        monkeypatch,
        "check_cdp_browser_for_authenticated_target",
        lambda _endpoint, _target_url: {"_target_id": "healthy-target"},
    )

    def fake_mark(target_url, challenge_id=None):
        marked.append((target_url, challenge_id))
        return {
            **state,
            "auth_complete_pending": True,
            "target_url": target_url,
            "challenge_id": challenge_id,
        }

    patch_loop_dependency(monkeypatch, "_mark_auth_complete_pending", fake_mark)
    monkeypatch.setattr(
        pc2_local_solver.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(SystemExit()),
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert marked == [("https://example.test/requested-page", "challenge-healthy-page")]
    assert len(pending_states) == 1
    assert pending_states[0]["challenge_id"] == "challenge-healthy-page"


def test_authenticated_target_probe_requires_every_matching_page_to_be_healthy(
    monkeypatch,
) -> None:
    summaries = iter(
        [
            {
                "authenticatedPage": True,
                "challengePresent": False,
                "loginRequired": False,
            },
            {
                "authenticatedPage": False,
                "challengePresent": True,
                "loginRequired": False,
            },
        ]
    )

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            self.target_url = target_url

        def _normalize_target_url(self, value):
            return str(value)

        def _solver_target_route(self, value):
            return str(value).split("?", 1)[0]

        def _remember_target_tab(self, _tab):
            return None

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            return next(summaries)

        def _close_solver_ws(self):
            return None

    monkeypatch.setattr(pc2_solver_cdp, "_create_probe_solver", FakeSolver)
    monkeypatch.setattr(
        pc2_solver_cdp,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "healthy",
                "type": "page",
                "url": "https://example.test/list?marker=1",
                "webSocketDebuggerUrl": "ws://example.test/healthy",
            },
            {
                "id": "challenge",
                "type": "page",
                "url": "https://example.test/list?marker=1",
                "webSocketDebuggerUrl": "ws://example.test/challenge",
            },
        ],
    )

    assert (
        pc2_local_solver.check_cdp_browser_for_authenticated_target(
            "http://127.0.0.1:9223",
            "https://example.test/list?marker=1",
        )
        is None
    )
