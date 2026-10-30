"""Page pressure never grants ownership over shared browser targets."""

from types import SimpleNamespace

import pytest

from src.captcha_solver import CaptchaSolver


def page(key, url="https://fixture.local/task", kind="page"):
    return {
        "id": key,
        "type": kind,
        "url": url,
        "webSocketDebuggerUrl": f"ws://fixture/{key}",
    }


def setup_solver(monkeypatch, owned=(), current=None, keepalive="blank", closes=True):
    solver = CaptchaSolver(target_url="https://sf-item.taobao.com/sf_item/42.htm")
    solver._opened_target_ids.update(owned)
    if current:
        solver._remember_target_tab(page(current))
    calls = []
    socket = SimpleNamespace(close=lambda: calls.append(("socket", current)))
    solver.ws = socket
    monkeypatch.setattr(solver, "_page_target_limit", lambda: 2)
    monkeypatch.setattr(
        solver, "_open_keepalive_tab", lambda: calls.append(("keepalive",)) or keepalive
    )
    monkeypatch.setattr(
        solver, "_close_cdp_target", lambda key: calls.append(("close", key)) or closes
    )
    return solver, calls, socket


@pytest.mark.parametrize(
    "foreign_url",
    [
        "https://sf.taobao.com/list/500000.htm?location_code=110000",
        "https://sf-item.taobao.com/sf_item/99.htm?x5step=1",
        "https://login.taobao.com/",
        "https://fixture.local/?__captcha_solver_bg=1",
        "about:blank",
    ],
)
@pytest.mark.parametrize("reserve", [False, True])
def test_no_owned_pages_means_no_lifecycle_side_effects(
    monkeypatch, foreign_url, reserve
):
    solver, calls, socket = setup_solver(monkeypatch, current="reused")
    result = solver._compact_cdp_pages_if_needed(
        [page("reused"), page("foreign", foreign_url)], reserve_for_new_page=reserve
    )
    assert result == {"triggered": False, "page_count": 2, "closed": 0}
    assert calls == []
    assert solver.ws is socket
    assert solver.target_id == "reused"
    assert solver.target_ws_url == "ws://fixture/reused"
    assert solver.current_target_url == "https://fixture.local/task"


def test_compaction_closes_only_recorded_page_ids_and_preserves_external_binding(
    monkeypatch,
):
    solver, calls, socket = setup_solver(
        monkeypatch, owned=("owned", "worker", "absent"), current="external"
    )
    result = solver._compact_cdp_pages_if_needed(
        [
            page("external"),
            page("owned", "https://other.local/redirect"),
            page("worker", kind="service_worker"),
        ]
    )
    assert result == {"triggered": True, "page_count": 2, "closed": 1}
    assert calls == [("close", "owned")]
    assert solver._opened_target_ids == {"worker", "absent"}
    assert solver.ws is socket
    assert solver.target_id == "external"


@pytest.mark.parametrize("closes", [False, True])
def test_current_binding_is_reset_only_after_successful_owned_close(
    monkeypatch, closes
):
    solver, calls, socket = setup_solver(
        monkeypatch, owned=("owned",), current="owned", closes=closes
    )
    result = solver._compact_cdp_pages_if_needed([page("external"), page("owned")])
    assert result["closed"] == int(closes)
    assert calls == [("close", "owned")] + ([("socket", "owned")] if closes else [])
    assert solver._opened_target_ids == (set() if closes else {"owned"})
    assert solver.ws is (None if closes else socket)
    assert solver.target_id == (None if closes else "owned")


def test_all_owned_pages_still_get_a_keepalive(monkeypatch):
    solver, calls, _ = setup_solver(monkeypatch, owned=("first", "second"))
    result = solver._compact_cdp_pages_if_needed([page("first"), page("second")])
    assert result == {
        "triggered": True,
        "page_count": 2,
        "closed": 2,
        "keepalive_target_id": "blank",
    }
    assert calls == [("keepalive",), ("close", "first"), ("close", "second")]


def test_failed_keepalive_preserves_an_owned_page_and_its_binding(monkeypatch):
    solver, calls, socket = setup_solver(
        monkeypatch, owned=("first", "second"), current="first", keepalive=None
    )
    result = solver._compact_cdp_pages_if_needed([page("first"), page("second")])
    assert result == {
        "triggered": True,
        "page_count": 2,
        "closed": 1,
        "preserved_target_id": "first",
    }
    assert calls == [("keepalive",), ("close", "second")]
    assert solver._opened_target_ids == {"first"}
    assert solver.ws is socket
    assert solver.target_id == "first"


@pytest.mark.parametrize("reserve, triggered", [(False, False), (True, True)])
def test_owned_pages_keep_original_reservation_threshold(
    monkeypatch, reserve, triggered
):
    solver, calls, _ = setup_solver(monkeypatch, owned=("owned",))
    result = solver._compact_cdp_pages_if_needed(
        [page("owned")], reserve_for_new_page=reserve
    )
    assert result["triggered"] is triggered
    assert result["closed"] == int(triggered)
    assert calls == ([("keepalive",), ("close", "owned")] if triggered else [])


def test_connect_at_page_limit_reuses_requested_external_page_without_closing_others(
    monkeypatch,
):
    solver, calls, _ = setup_solver(monkeypatch)
    solver.ws = None
    target = page("requested", solver.target_url)
    tabs = [
        target,
        page("seed", "https://sf.taobao.com/list/500000.htm"),
        page("manual", "https://login.taobao.com/"),
    ]
    monkeypatch.setattr(solver, "_get_json", lambda _endpoint: tabs)
    monkeypatch.setattr(solver, "_connect_to_target", lambda *_args: True)
    monkeypatch.setattr(solver, "_open_target_tab", lambda: pytest.fail("must reuse"))
    assert solver.connect_tab() is True
    assert solver.target_id == "requested"
    assert calls == []
