from tools import pc2_solver_cdp
from tools import pc2_solver_execution
from tools.test.pc2_local_solver_test_context import *
from tools.test.pc2_loop_test_dependencies import patch_loop_dependency


def test_run_solver_local_with_deadline_exits_if_child_survives_kill(
    monkeypatch,
) -> None:
    events: list[dict[str, object]] = []

    class Connection:
        def close(self) -> None:
            return None

    class Process:
        exitcode = None

        def start(self) -> None:
            return None

        def join(self, _timeout) -> None:
            return None

        def is_alive(self) -> bool:
            return True

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

        def close(self) -> None:
            raise AssertionError("a live process handle cannot be closed")

    class Context:
        def Pipe(self, *, duplex):
            assert duplex is False
            return Connection(), Connection()

        def Process(self, **_kwargs):
            return Process()

    monkeypatch.setattr(
        pc2_local_solver.multiprocessing, "get_context", lambda method: Context()
    )
    monkeypatch.setattr(pc2_solver_execution, "SOLVER_TERMINATE_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(
        pc2_solver_execution, "log_event", lambda event: events.append(event)
    )

    with pytest.raises(SystemExit, match="survived terminate and kill"):
        pc2_local_solver.run_solver_local_with_deadline(
            "http://127.0.0.1:9223",
            "https://example.test/challenge",
            timeout_seconds=1,
        )

    assert events[-1] == {
        "kind": "local_solver_execution_timeout",
        "timeout_seconds": 1.0,
        "terminated": False,
    }


def test_run_solver_local_with_deadline_real_spawn_returns_for_unreachable_cdp() -> (
    None
):
    assert (
        pc2_local_solver.run_solver_local_with_deadline(
            "http://127.0.0.1:1",
            "https://example.invalid/challenge",
            timeout_seconds=15,
        )
        is False
    )


def test_cdp_slider_probe_scans_pages_and_returns_target_identity(monkeypatch) -> None:
    sockets: list[FakeWebSocket] = []

    class FakeWebSocket:
        def __init__(self, ws_url: str) -> None:
            self.ws_url = ws_url
            self.last_message: dict[str, object] = {}
            self.closed = False

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message = json.loads(payload)

        def recv(self) -> str:
            message_id = self.last_message["id"]
            if self.last_message["method"] == "Runtime.evaluate":
                found = self.ws_url.endswith("/slider-target")
                value = {
                    "found": found,
                    "x": 10,
                    "y": 20,
                    "width": 42,
                    "height": 30,
                    "selector": "#nc_1_n1z",
                }
                return json.dumps(
                    {"id": message_id, "result": {"result": {"value": value}}}
                )
            return json.dumps({"id": message_id, "result": {}})

        def close(self) -> None:
            self.closed = True

    tabs = [
        {
            "id": "worker-target",
            "type": "worker",
            "url": "https://example.test/background-worker.js",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/worker-target",
        },
        {
            "id": "plain-target",
            "type": "page",
            "url": "https://example.test/plain",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/plain-target",
        },
        {
            "id": "slider-target",
            "type": "page",
            "url": "https://example.test/visible-slider?__captcha_solver_bg=1",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/slider-target",
        },
    ]
    monkeypatch.setattr(pc2_solver_cdp, "fetch_json", lambda *_args, **_kwargs: tabs)

    def fake_create_connection(ws_url: str, **_kwargs: object) -> FakeWebSocket:
        socket = FakeWebSocket(ws_url)
        sockets.append(socket)
        return socket

    import websocket

    monkeypatch.setattr(websocket, "create_connection", fake_create_connection)

    result = pc2_local_solver.check_cdp_browser_for_slider("http://127.0.0.1:9223")

    assert result is not None
    assert result["selector"] == "#nc_1_n1z"
    assert result["_target_id"] == "slider-target"
    assert (
        result["_target_url"]
        == "https://example.test/visible-slider?__captcha_solver_bg=1"
    )
    assert result["_target_ws_url"] == "ws://127.0.0.1:9223/devtools/page/slider-target"
    assert [socket.ws_url for socket in sockets] == [
        "ws://127.0.0.1:9223/devtools/page/plain-target",
        "ws://127.0.0.1:9223/devtools/page/slider-target",
    ]
    assert all(socket.closed for socket in sockets)


def test_cdp_challenge_probe_returns_existing_target_identity(monkeypatch) -> None:
    challenge = {
        "id": "punish-target",
        "type": "page",
        "title": "验证码拦截",
        "url": "https://sf.taobao.com/list/50025969__2.htm",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/punish-target",
    }
    monkeypatch.setattr(
        pc2_solver_cdp,
        "fetch_json",
        lambda *_args, **_kwargs: [
            {"id": "blank", "type": "page", "url": "about:blank"},
            challenge,
        ],
    )

    result = pc2_local_solver.check_cdp_browser_for_challenge_page(
        "http://127.0.0.1:9223"
    )

    assert result == {
        "_target_id": "punish-target",
        "_target_url": challenge["url"],
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/punish-target",
    }


def test_cdp_challenge_probe_prefers_requested_route_over_unrelated_detail(
    monkeypatch,
) -> None:
    unrelated = {
        "id": "detail-challenge",
        "type": "page",
        "title": "验证码拦截",
        "url": "https://sf-item.taobao.com//sf_item/601294677898.htm/_____tmd_____/punish",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/detail-challenge",
    }
    requested = {
        "id": "list-challenge",
        "type": "page",
        "title": "验证码拦截",
        "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/list-challenge",
    }
    monkeypatch.setattr(
        pc2_solver_cdp,
        "fetch_json",
        lambda *_args, **_kwargs: [unrelated, requested],
    )

    result = pc2_local_solver.check_cdp_browser_for_challenge_page(
        "http://127.0.0.1:9223",
        target_url=(
            "https://sf.taobao.com/list/50025969__2.htm"
            "?auction_start_seg=-1&location_code=110114&page=4&st_param=5"
        ),
    )

    assert result["_target_id"] == "list-challenge"


@pytest.mark.parametrize(
    "evidence_key", ["challengePresent", "explicitFailure", "hardBlock", "hasSlider"]
)
def test_cdp_challenge_probe_uses_route_scoped_dom_evidence(
    monkeypatch, evidence_key
) -> None:
    closed_targets: list[str | None] = []

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            self.current_target = None

        def _solver_target_route(self, value):
            return str(value or "").split("?", 1)[0]

        def _remember_target_tab(self, tab):
            self.current_target = tab.get("id")

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            assert self.current_target == "requested"
            return {evidence_key: True}

        def _close_solver_ws(self):
            closed_targets.append(self.current_target)

    monkeypatch.setattr(pc2_solver_cdp, "_create_probe_solver", FakeSolver)
    monkeypatch.setattr(
        pc2_solver_cdp,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "unrelated",
                "type": "page",
                "title": "normal",
                "url": "https://example.test/unrelated",
                "webSocketDebuggerUrl": "ws://example.test/unrelated",
            },
            {
                "id": "requested",
                "type": "page",
                "title": "normal",
                "url": "https://example.test/requested?state=normal",
                "webSocketDebuggerUrl": "ws://example.test/requested",
            },
        ],
    )

    result = pc2_local_solver.check_cdp_browser_for_challenge_page(
        "http://127.0.0.1:9223",
        target_url="https://example.test/requested?from=api",
    )

    assert result == {
        "_target_id": "requested",
        "_target_url": "https://example.test/requested?state=normal",
        "_target_ws_url": "ws://example.test/requested",
        "_challenge_evidence": [evidence_key],
    }
    assert "requested" in closed_targets


def test_cdp_challenge_probe_stays_fail_closed_without_dom_evidence(
    monkeypatch,
) -> None:
    close_calls = 0

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            pass

        def _solver_target_route(self, value):
            return str(value or "").split("?", 1)[0]

        def _remember_target_tab(self, _tab):
            pass

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            return {"authenticatedPage": False, "challengePresent": False}

        def _close_solver_ws(self):
            nonlocal close_calls
            close_calls += 1

    monkeypatch.setattr(pc2_solver_cdp, "_create_probe_solver", FakeSolver)
    monkeypatch.setattr(
        pc2_solver_cdp,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "requested",
                "type": "page",
                "title": "normal",
                "url": "https://example.test/requested",
                "webSocketDebuggerUrl": "ws://example.test/requested",
            }
        ],
    )

    assert (
        pc2_local_solver.check_cdp_browser_for_challenge_page(
            "http://127.0.0.1:9223",
            target_url="https://example.test/requested",
        )
        is None
    )
    assert close_calls >= 1


def test_paused_api_trigger_probes_and_passes_existing_slider_target(
    monkeypatch,
) -> None:
    probe_target = {
        "found": True,
        "_target_id": "slider-target",
        "_target_url": "https://example.test/visible-slider",
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/slider-target",
    }
    captured: list[dict[str, object]] = []
    probed_urls: list[str] = []
    solved_urls: list[str] = []
    state = pc2_local_solver._default_fallback_state()
    state["slider_attempts"] = 4
    state["challenge_id"] = "detail-challenge"
    state["scope"] = "detail"

    aggregate_status = {
        # The latest reporter is seed, while the persisted solver attempt still
        # owns the independent detail challenge.  Revalidation must not switch
        # scopes at the execution boundary.
        "paused": True,
        "running": False,
        "manual_required": False,
        "challenge_id": "seed-challenge",
        "last_request": {"target_url": "https://seed.example.test/list"},
        "scopes": {
            "seed": {
                "challenge_id": "seed-challenge",
                "first_seen_epoch": 200.0,
                "paused": True,
                "last_request": {"target_url": "https://seed.example.test/list"},
            },
            "detail": {
                "challenge_id": "detail-challenge",
                "first_seen_epoch": 100.0,
                "paused": True,
                "last_request": {
                    "target_url": "https://detail.example.test/item",
                    "cdp_endpoint": pc2_local_solver.DEFAULT_CDP_ENDPOINT,
                },
            },
        },
    }

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
        lambda _api: aggregate_status,
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

    def fake_slider_probe(_endpoint, *, target_url=None):
        probed_urls.append(target_url)
        return probe_target

    patch_loop_dependency(
        monkeypatch, "check_cdp_browser_for_slider", fake_slider_probe
    )

    def fake_run_solver(_endpoint, target_url, **kwargs) -> bool:
        solved_urls.append(target_url)
        captured.append(kwargs)
        raise SystemExit

    patch_loop_dependency(
        monkeypatch, "run_solver_local_with_deadline", fake_run_solver
    )

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert captured[0]["probe_target"] == probe_target
    assert captured[0]["drag_profile_offset"] == 1
    assert probed_urls == ["https://detail.example.test/item"]
    assert solved_urls == ["https://detail.example.test/item"]


def test_solver_request_target_urls_preserve_priority_and_remove_duplicates() -> None:
    last_request = {
        "challenge_target_url": "https://detail.example.test/item",
        "target_url": "https://seed.example.test/list",
        "url": "https://seed.example.test/list",
    }

    assert pc2_local_solver.solver_request_target_urls(last_request) == [
        "https://detail.example.test/item",
        "https://seed.example.test/list",
    ]
    assert pc2_local_solver.solver_request_target_url(last_request) == (
        "https://detail.example.test/item"
    )
