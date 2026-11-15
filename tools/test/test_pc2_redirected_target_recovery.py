"""A navigation ACK followed by a redirect must not leak another page per poll."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src import captcha_cdp
from src.captcha_deferral import TargetNavigationUnconfirmed
from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_execution as execution
from tools.pc2_solver_maintenance import bind_pending_navigation
from tools.test.maintenance_deferral_fixtures import CDP
from tools.test.pc2_maintenance_budget_fixtures import TARGETS


@pytest.fixture
def redirected_browser(monkeypatch):
    directory = []
    creates, navigations = [], []

    def create(*args, **kwargs):
        tab = {
            "id": f"owned-{len(creates)}",
            "type": "page",
            "url": "about:blank",
            "webSocketDebuggerUrl": "ws://localhost/devtools/page/owned",
        }
        creates.append(tab["id"])
        directory.append(tab)
        return SimpleNamespace(status_code=200, json=lambda: deepcopy(tab))

    def send(solver, method, params=None, **kwargs):
        assert method == "Page.navigate"
        navigations.append(solver.target_id)
        for tab in directory:
            if tab["id"] == solver.target_id:
                tab["url"] = "https://sf.taobao.com/"
        return {"frameId": "frame", "loaderId": str(len(navigations))}

    monkeypatch.setattr(captcha_cdp.requests, "put", create)
    monkeypatch.setattr(CaptchaSolver, "_connect_to_target", lambda *_: True)
    monkeypatch.setattr(CaptchaSolver, "_send_cdp", send)
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: deepcopy(directory))
    return SimpleNamespace(
        directory=directory, creates=creates, navigations=navigations
    )


@pytest.mark.parametrize("scope", TARGETS)
def test_acknowledged_navigation_redirect_reuses_one_owned_page(
    redirected_browser, scope
):
    browser = redirected_browser
    target = TARGETS[scope]
    result = execution.rebuild_missing_challenge_target(CDP, target)
    assert result["opened"] is True
    pending = bind_pending_navigation(result["probe_target"], "generation")
    assert pending["_maintenance_owned"] is True
    for _ in range(10):
        result = execution.rebuild_missing_challenge_target(
            CDP, target, pending_target=pending
        )
        assert result["opened"] is False
        assert result["reason"] == "redirected_target_reused"
        pending = bind_pending_navigation(result["probe_target"], "generation")
    assert browser.creates == ["owned-0"]
    assert browser.navigations == ["owned-0"] * 11
    assert len(browser.directory) == 1


def test_later_redirect_retains_ownership_after_matching_route(redirected_browser):
    browser = redirected_browser
    first = execution.rebuild_missing_challenge_target(CDP, TARGETS["seed"])
    browser.directory[0]["url"] = TARGETS["seed"]
    present = execution.rebuild_missing_challenge_target(
        CDP, TARGETS["seed"], pending_target=first["probe_target"]
    )
    assert present["reason"] == "request_target_already_present"
    assert present["probe_target"]["_maintenance_owned"] is True
    browser.directory[0]["url"] = "https://sf.taobao.com/"
    reused = execution.rebuild_missing_challenge_target(
        CDP, TARGETS["seed"], pending_target=present["probe_target"]
    )
    assert reused["reason"] == "redirected_target_reused"
    assert browser.creates == ["owned-0"]


@pytest.mark.parametrize(
    "url", ["https://login.taobao.com/", "https://example.invalid/unrelated"]
)
def test_owned_login_or_external_page_is_not_navigated_or_multiplied(
    redirected_browser, url
):
    browser = redirected_browser
    first = execution.rebuild_missing_challenge_target(CDP, TARGETS["seed"])
    browser.directory[0]["url"] = url
    result = execution.rebuild_missing_challenge_target(
        CDP, TARGETS["seed"], pending_target=first["probe_target"]
    )
    assert result["reason"] == "owned_target_relocated"
    assert browser.creates == browser.navigations == ["owned-0"]


def test_disappeared_owned_page_can_be_recreated(redirected_browser):
    first = execution.rebuild_missing_challenge_target(CDP, TARGETS["seed"])
    redirected_browser.directory.clear()
    result = execution.rebuild_missing_challenge_target(
        CDP, TARGETS["seed"], pending_target=first["probe_target"]
    )
    assert result["opened"] is True
    assert redirected_browser.creates == ["owned-0", "owned-1"]


def test_borrowed_homepage_is_never_navigated(redirected_browser):
    redirected_browser.directory.append(
        {"id": "borrowed", "type": "page", "url": "https://sf.taobao.com/"}
    )
    execution.rebuild_missing_challenge_target(CDP, TARGETS["seed"])
    assert redirected_browser.navigations == ["owned-0"]


def test_failed_reuse_keeps_ownership_for_next_poll(monkeypatch, redirected_browser):
    first = execution.rebuild_missing_challenge_target(CDP, TARGETS["seed"])
    monkeypatch.setattr(CaptchaSolver, "_connect_to_target", lambda *_: False)
    result = execution.rebuild_missing_challenge_target(
        CDP, TARGETS["seed"], pending_target=first["probe_target"]
    )
    assert result["reason"] == "missing_target_open_failed"
    assert result["probe_target"] == first["probe_target"]
    assert redirected_browser.creates == ["owned-0"]


@pytest.mark.parametrize(
    "url", ["https://login.taobao.com/", "https://example.invalid/unrelated"]
)
def test_lost_reuse_ack_keeps_owned_provenance(monkeypatch, redirected_browser, url):
    first = execution.rebuild_missing_challenge_target(CDP, TARGETS["seed"])

    def lose_ack(*args):
        redirected_browser.directory[0]["url"] = url
        raise TargetNavigationUnconfirmed()

    monkeypatch.setattr(
        CaptchaSolver, "_prepare_opened_target_before_navigation", lose_ack
    )
    deferred = execution.rebuild_missing_challenge_target(
        CDP, TARGETS["seed"], pending_target=first["probe_target"]
    )
    assert deferred["probe_target"]["_maintenance_owned"] is True
    execution.rebuild_missing_challenge_target(
        CDP, TARGETS["seed"], pending_target=deferred["probe_target"]
    )
    assert redirected_browser.creates == ["owned-0"]
