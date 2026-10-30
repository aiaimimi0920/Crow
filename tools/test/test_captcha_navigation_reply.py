"""A CDP reply is not a successful navigation when it explicitly reports failure."""

from unittest.mock import Mock

import pytest

from src.captcha_deferral import TargetNavigationUnconfirmed
from tools.test.test_captcha_target_open_recovery import opening_solver

INVALID_REPLIES = (
    {"frameId": "frame", "loaderId": "loader", "errorText": "net::ERR_ABORTED SECRET"},
    {"frameId": "frame", "errorText": ""},
    {"frameId": "frame", "isDownload": True},
    {"frameId": "frame", "isDownload": 1},
    {"frameId": "frame", "loaderId": ""},
    {"frameId": "frame", "loaderId": None},
    {"frameId": ""},
    {"frameId": 1},
    {},
    [],
    "SECRET",
    True,
)


@pytest.mark.parametrize("reply", INVALID_REPLIES)
def test_failed_or_invalid_navigation_reply_is_not_accepted(monkeypatch, caplog, reply):
    solver, payload, put = opening_solver(monkeypatch)
    connect = Mock(return_value=True)
    navigate = Mock(return_value=reply)
    monkeypatch.setattr(solver, "_connect_to_target", connect)
    monkeypatch.setattr(solver, "_send_cdp", navigate)

    with pytest.raises(TargetNavigationUnconfirmed):
        solver._open_target_tab()

    assert put.call_count == connect.call_count == navigate.call_count == 1
    assert solver._opened_target_ids == {"owned-tab"}
    assert payload["url"] == "about:blank"
    assert solver.current_target_url == "about:blank"
    assert "SECRET" not in caplog.text


@pytest.mark.parametrize("reply", INVALID_REPLIES)
def test_invalid_navigation_exits_real_solve_without_input_or_replay(
    monkeypatch, reply
):
    solver, _, put = opening_solver(monkeypatch)
    socket = Mock()
    navigate = Mock(return_value=reply)
    monkeypatch.setattr(solver, "_get_json", lambda _: [])
    monkeypatch.setattr(
        solver, "_connect_to_target", lambda *_: setattr(solver, "ws", socket) or True
    )
    monkeypatch.setattr(solver, "_send_cdp", navigate)
    forbidden = Mock(side_effect=AssertionError("unconfirmed navigation must defer"))
    for name in (
        "_headed_playwright_enabled",
        "_close_cdp_target",
        "_reload_page",
        "_page_challenge_summary",
        "_do_drag",
        "_do_drag_os",
    ):
        monkeypatch.setattr(solver, name, forbidden)
    monkeypatch.setattr(solver, "_wait_interruptibly", lambda _: None)

    assert solver.solve(max_attempts=3) is False

    assert solver.last_failure_reason == "cdp_unavailable"
    assert put.call_count == navigate.call_count == 1
    assert solver._opened_target_ids == {"owned-tab"}
    assert solver._solve_budget is None and not solver.lock.locked()
    assert solver.ws is None
    socket.close.assert_called_once_with()
    forbidden.assert_not_called()


@pytest.mark.parametrize("loader", [False, True])
def test_valid_navigation_ack_preserves_optional_same_document_loader(
    monkeypatch, loader
):
    solver, payload, put = opening_solver(monkeypatch)
    reply = {"frameId": "frame", "isDownload": False}
    if loader:
        reply["loaderId"] = "loader"
    monkeypatch.setattr(solver, "_connect_to_target", Mock(return_value=True))
    monkeypatch.setattr(solver, "_send_cdp", Mock(return_value=reply))

    assert solver._open_target_tab() is payload
    assert put.call_count == 1
    assert solver.current_target_url == solver.target_url
