"""Transport retries preserve recovery opportunities without terminal idle waits."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import websocket

from src import captcha_cdp_command
from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver


@pytest.mark.parametrize(
    "target",
    [
        "https://sf.taobao.com/list/123.htm?page=2",
        "https://sf-item.taobao.com/sf_item/123.htm",
        "https://fixture.invalid/challenge",
    ],
)
def test_same_endpoint_can_recover_with_a_new_socket_in_the_same_pass(
    monkeypatch, target
):
    now = [0.0]
    monkeypatch.setattr(
        captcha_cdp_command, "time", SimpleNamespace(monotonic=lambda: now[0])
    )
    solver = CaptchaSolver(target_url=target, cdp_endpoint="http://cdp.invalid:9223")
    page = {
        "id": "cached",
        "type": "page",
        "url": target,
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/cached",
    }
    solver._remember_target_tab(page)
    solver._get_json = Mock(return_value=[page])
    solver._prune_duplicate_challenge_tabs = Mock(return_value={"closed": 0})
    solver._compact_cdp_pages_if_needed = Mock(return_value={"triggered": False})
    solver._open_target_tab = Mock(side_effect=AssertionError("no extra renderer"))
    solver._close_cdp_target = Mock(side_effect=AssertionError("no page close"))
    budget = SolveBudget(deadline=100, clock=lambda: now[0])
    solver._solve_budget = budget
    sockets = []

    class Socket:
        timeout = 5
        last_id = None
        closed = False

        def gettimeout(self):
            return self.timeout

        def settimeout(self, value):
            self.timeout = value

        def send(self, raw):
            message = json.loads(raw)
            assert not message["method"].startswith("Input.")
            assert message["method"] != "Page.navigate"
            self.last_id = message["id"]

        def recv(self):
            if self is sockets[0]:
                now[0] += self.timeout
                raise websocket.WebSocketTimeoutException("fixture renderer timeout")
            return json.dumps({"id": self.last_id, "result": {}})

        def close(self):
            self.closed = True

    def connect(endpoint, **_kwargs):
        assert endpoint == "ws://cdp.invalid:9223/devtools/page/cached"
        socket = Socket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr(websocket, "create_connection", connect)

    assert solver.connect_tab() is True
    assert len(sockets) == 2 and sockets[0].closed
    assert now[0] == pytest.approx(5)
    assert solver.last_failure_reason is None and solver.ws is sockets[1]
    assert solver.target_id == "cached"
    assert solver._solve_budget is budget and budget.deadline == 100
    assert solver._opened_target_ids == set()
    solver._open_target_tab.assert_not_called()
    solver._close_cdp_target.assert_not_called()


@pytest.mark.parametrize("attempts", [1, 2, 3])
@pytest.mark.parametrize("failure_reason", ["cdp_unavailable", None])
def test_final_attach_failure_keeps_transport_reason_without_terminal_retry_sleep(
    monkeypatch, attempts, failure_reason
):
    solver = CaptchaSolver(target_url="https://sf-item.taobao.com/sf_item/123.htm")
    now = [0.0]
    budget = SolveBudget(deadline=100, clock=lambda: now[0])
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_kwargs: budget)
    solver._preflight_current_challenge = Mock(return_value={"connected": False})
    solver._close_owned_target_tabs = Mock()
    solver._find_slider = Mock()
    solver._do_drag = Mock()
    solver._send_cdp = Mock(return_value=None)
    solver._headed_playwright_enabled = Mock(return_value=False)
    waits = []

    def failed_attach():
        now[0] += 5
        solver.last_failure_reason = failure_reason
        return False

    def wait(seconds):
        waits.append(seconds)
        now[0] += seconds

    solver.connect_tab = Mock(side_effect=failed_attach)
    solver._wait_interruptibly = wait

    assert solver.solve(max_attempts=attempts) is False
    assert solver.last_failure_reason == (failure_reason or "max_attempts_exceeded")
    assert waits == [5] * (attempts - 1)
    assert now[0] == 5 * (2 * attempts - 1)
    assert solver.connect_tab.call_count == attempts
    assert budget.deadline == 100
    assert not solver.lock.locked() and solver._solve_budget is None
    solver._find_slider.assert_not_called()
    solver._do_drag.assert_not_called()


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
def test_stop_on_final_attach_failure_keeps_priority_and_original_budget(
    monkeypatch, reason
):
    solver = CaptchaSolver(target_url="https://sf-item.taobao.com/sf_item/123.htm")
    now = [0.0]
    budget = SolveBudget(deadline=100, clock=lambda: now[0])
    monkeypatch.setattr("src.captcha_budget.SolveBudget", lambda **_kwargs: budget)
    solver._preflight_current_challenge = Mock(return_value={"connected": False})
    solver._close_owned_target_tabs = Mock()
    solver._headed_playwright_enabled = Mock(return_value=False)
    solver._wait_interruptibly = Mock()
    solver._recover_authenticated_list_page = Mock(return_value=False)

    def failed_attach():
        solver.last_failure_reason = "cdp_unavailable"
        if reason == "cancelled":
            budget.event.set()
        else:
            now[0] = 100
        return False

    solver.connect_tab = failed_attach
    assert solver.solve(max_attempts=1) is False
    assert solver.last_failure_reason == budget.reason == reason
    assert budget.deadline == 100
    assert not solver.lock.locked() and solver._solve_budget is None
    solver._wait_interruptibly.assert_not_called()
    solver._recover_authenticated_list_page.assert_not_called()
