"""A failed post-lifecycle directory refresh is not an empty or stale directory."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveBudget
from src.captcha_solver import CaptchaSolver

TARGETS = [
    "https://sf-item.taobao.com/sf_item/123.htm",
    "https://sf.taobao.com/list/500000.htm?location_code=110000&page=2",
    "https://fixture.local/task",
]
STAGES = ["cached_prune", "initial_compaction", "selection_prune", "reopen_compaction"]


def page(key, url):
    return {
        "id": key,
        "type": "page",
        "url": url,
        "webSocketDebuggerUrl": f"ws://fixture/{key}",
    }


def setup(monkeypatch, stage, target, refreshed=None):
    solver = CaptchaSolver(target_url=target)
    requested = page("bound", target)
    initial = (
        [requested]
        if stage in {"cached_prune", "selection_prune"}
        else [page("foreign", "https://fixture.local/other")]
    )
    if stage == "cached_prune":
        solver._remember_target_tab(requested)
    replies = iter([initial, refreshed])
    solver._get_json = Mock(side_effect=lambda _endpoint: next(replies, None))
    solver._connect_to_target = Mock(return_value=True)
    solver._connect_opened_target = Mock(return_value=True)
    solver._open_target_tab = Mock(return_value=page("new", target))
    prunings = iter(
        [{"closed": int(stage in {"cached_prune", "selection_prune"}), "kept": "bound"}]
    )
    solver._prune_duplicate_challenge_tabs = Mock(
        side_effect=lambda _tabs: next(prunings, {"closed": 0, "kept": "bound"})
    )
    compactions = iter(
        [{"triggered": False}, {"triggered": True}]
        if stage == "reopen_compaction"
        else [{"triggered": stage == "initial_compaction"}]
    )
    solver._compact_cdp_pages_if_needed = Mock(
        side_effect=lambda *_args, **_kwargs: next(compactions, {"triggered": False})
    )
    return solver


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("target", TARGETS)
def test_unavailable_refresh_never_opens_or_connects_using_stale_metadata(
    monkeypatch, stage, target
):
    solver = setup(monkeypatch, stage, target)

    assert solver.connect_tab() is False

    assert solver.last_failure_reason == "cdp_unavailable"
    solver._open_target_tab.assert_not_called()
    solver._connect_opened_target.assert_not_called()
    solver._connect_to_target.assert_not_called()
    assert solver._get_json.call_count == 2


@pytest.mark.parametrize("stage", STAGES)
def test_valid_empty_refresh_keeps_the_original_open_target_path(monkeypatch, stage):
    solver = setup(monkeypatch, stage, TARGETS[0], refreshed=[])

    assert solver.connect_tab() is True

    solver._open_target_tab.assert_called_once_with()
    solver._connect_opened_target.assert_called_once()
    solver._connect_to_target.assert_not_called()
    assert solver.last_failure_reason is None


@pytest.mark.parametrize("stage", STAGES[:3])
def test_valid_refresh_can_reuse_the_current_requested_page(monkeypatch, stage):
    solver = setup(
        monkeypatch, stage, TARGETS[0], refreshed=[page("fresh", TARGETS[0])]
    )

    assert solver.connect_tab() is True

    solver._open_target_tab.assert_not_called()
    solver._connect_to_target.assert_called_once_with("ws://fixture/fresh", "")
    assert solver.target_id == "fresh"


@pytest.mark.parametrize("reason", ["cancelled", "deadline_exceeded"])
@pytest.mark.parametrize("stage", STAGES)
def test_stop_during_refresh_retains_priority(monkeypatch, stage, reason):
    solver = setup(monkeypatch, stage, TARGETS[0])
    clock = [0.0]
    solver._solve_budget = SolveBudget(deadline=1.0, clock=lambda: clock[0])
    solver.cancel_checker = lambda: reason == "cancelled" and clock[0] >= 2
    directory = solver._get_json.side_effect

    def read(endpoint):
        result = directory(endpoint)
        if result is None:
            clock[0] = 2.0
        return result

    solver._get_json.side_effect = read
    assert solver.connect_tab() is False
    assert solver.last_failure_reason == reason
    solver._open_target_tab.assert_not_called()
    solver._connect_to_target.assert_not_called()


def test_real_owned_compaction_does_not_reopen_after_directory_outage(monkeypatch):
    solver = CaptchaSolver(target_url=TARGETS[0])
    solver._opened_target_ids.add("owned")
    solver._page_target_limit = Mock(return_value=2)
    solver._get_json = Mock(
        side_effect=[[page("owned", "https://fixture.local/owned")], None]
    )
    solver._open_keepalive_tab = Mock(return_value="keepalive")
    solver._close_cdp_target = Mock(return_value=True)
    solver._open_target_tab = Mock()
    solver._connect_to_target = Mock()

    assert solver.connect_tab() is False

    solver._open_keepalive_tab.assert_called_once_with()
    solver._close_cdp_target.assert_called_once_with("owned")
    solver._open_target_tab.assert_not_called()
    solver._connect_to_target.assert_not_called()
    assert solver.last_failure_reason == "cdp_unavailable"
    assert solver._opened_target_ids == set()


@pytest.mark.parametrize("target", TARGETS[:2])
def test_real_duplicate_pruning_cannot_connect_with_the_old_directory(target):
    solver = CaptchaSolver(target_url=target)
    separator = "&" if "?" in target else "?"
    tabs = [
        page("keep", target + separator + "x5step=1"),
        page("duplicate", target + separator + "x5step=2"),
    ]
    solver._get_json = Mock(side_effect=[tabs, None])
    solver._close_cdp_target = Mock(return_value=True)
    solver._open_target_tab = Mock()
    solver._connect_to_target = Mock()

    assert solver.connect_tab() is False

    solver._close_cdp_target.assert_called_once_with("duplicate")
    solver._open_target_tab.assert_not_called()
    solver._connect_to_target.assert_not_called()
    assert solver.last_failure_reason == "cdp_unavailable"


def test_failed_cached_connect_does_not_retry_from_an_unavailable_recheck():
    solver = CaptchaSolver(target_url=TARGETS[0])
    requested = page("bound", TARGETS[0])
    solver._remember_target_tab(requested)
    solver._get_json = Mock(side_effect=[[requested], None])
    solver._connect_to_target = Mock(side_effect=[False, True])
    solver._open_target_tab = Mock()

    assert solver.connect_tab() is False

    solver._connect_to_target.assert_called_once_with(
        "ws://fixture/bound", "cached solver target"
    )
    solver._open_target_tab.assert_not_called()
    assert solver.last_failure_reason == "cdp_unavailable"


@pytest.mark.parametrize("stage", STAGES)
def test_failed_refresh_closes_only_the_solver_socket(monkeypatch, stage):
    solver = setup(monkeypatch, stage, TARGETS[0])
    socket = SimpleNamespace(close=Mock())
    solver.ws = socket
    solver._opened_target_ids.add("owned")
    solver._close_cdp_target = Mock()

    assert solver.connect_tab() is False

    socket.close.assert_called_once_with()
    assert solver.ws is None
    solver._close_cdp_target.assert_not_called()
    assert solver._opened_target_ids == {"owned"}


@pytest.mark.parametrize("target", TARGETS[:2])
def test_full_solve_cannot_navigate_the_stale_socket_after_real_pruning(target):
    solver = CaptchaSolver(target_url=target)
    separator = "&" if "?" in target else "?"
    tabs = [
        page("keep", target + separator + "x5step=1"),
        page("duplicate", target + separator + "x5step=2"),
    ]
    solver._remember_target_tab(tabs[0])
    solver._get_json = Mock(side_effect=[tabs, None, tabs, None])
    solver._close_cdp_target = Mock(return_value=True)
    solver._connect_to_target = Mock(return_value=False)
    solver._wait_interruptibly = Mock()
    solver._page_challenge_summary = Mock(return_value={})
    solver._find_slider = Mock(side_effect=AssertionError("No slider input allowed"))
    sent = []

    def receive():
        request = sent[-1]
        result = (
            {"result": {"value": target}}
            if request["method"] == "Runtime.evaluate"
            else {}
        )
        return json.dumps({"id": request["id"], "result": result})

    socket = SimpleNamespace(
        send=lambda raw: sent.append(json.loads(raw)),
        recv=receive,
        gettimeout=lambda: 5,
        settimeout=Mock(),
        close=Mock(),
    )
    solver.ws = socket

    assert solver.solve(max_attempts=1) is False

    assert sent == []
    socket.close.assert_called_once_with()
    assert solver.ws is None and solver.last_failure_reason == "cdp_unavailable"
    assert solver.target_id == "keep" and solver._opened_target_ids == set()
    assert solver._get_json.call_count == 4
    solver._connect_to_target.assert_not_called()
    solver._find_slider.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def test_full_solve_keeps_failure_retry_and_page_operations_bounded(monkeypatch):
    solver = setup(monkeypatch, "initial_compaction", TARGETS[0])
    solver._close_cdp_target = Mock()
    solver._recover_authenticated_list_page = Mock(return_value=False)
    solver._find_slider = Mock()
    solver._solve_with_ddddocr = Mock()
    solver._solve_with_playwright_stealth = Mock()

    assert solver.solve(max_attempts=1) is False

    assert solver.last_failure_reason == "cdp_unavailable"
    solver._open_target_tab.assert_not_called()
    solver._find_slider.assert_not_called()
    solver._solve_with_ddddocr.assert_not_called()
    solver._solve_with_playwright_stealth.assert_not_called()
    assert solver._opened_target_ids == set()
    solver._close_cdp_target.assert_not_called()
    assert not solver.lock.locked() and solver._solve_budget is None


def test_next_call_can_revalidate_instead_of_latching_failure(monkeypatch):
    solver = setup(monkeypatch, "cached_prune", TARGETS[0])
    assert solver.connect_tab() is False
    solver._get_json = Mock(return_value=[page("bound", TARGETS[0])])
    solver._prune_duplicate_challenge_tabs.return_value = {"closed": 0}
    assert solver.connect_tab() is True
    solver._connect_to_target.assert_called_once_with(
        "ws://fixture/bound", "cached solver target"
    )


def test_initial_directory_outage_still_allows_existing_bound_cache(monkeypatch):
    solver = CaptchaSolver(target_url=TARGETS[0])
    solver._remember_target_tab(page("bound", TARGETS[0]))
    solver._get_json = Mock(return_value=None)
    solver._connect_to_target = Mock(return_value=True)
    solver._open_target_tab = Mock()
    assert solver.connect_tab() is True
    solver._open_target_tab.assert_not_called()
