"""A recovered list must remain the same regional, sorted collection page."""

from urllib.parse import parse_qs, urlsplit

import pytest

from src.captcha_solver import CaptchaSolver
from src.collection.adapters.taobao_auth_target import same_auth_target
from tools import pc2_local_solver as solver
from tools import pc2_solver_cdp, pc2_solver_execution, pc2_solver_scope

TARGET = "https://sf.taobao.com/list/200782003__2.htm?location_code=120113&st_param=4&auction_start_seg=-1&page=5"
CHALLENGE = (
    TARGET.replace(".htm?", ".htm/_____tmd_____/punish?") + "&x5secdata=discarded"
)


@pytest.mark.parametrize("report", ["notify_manual_challenge", "notify_solver_blocked"])
def test_report_keeps_collection_identity_without_challenge_credentials(
    monkeypatch, report
):
    requests = []
    monkeypatch.setattr(
        pc2_solver_scope,
        "post_json",
        lambda _url, payload, **_kwargs: requests.append(payload) or {},
    )
    status = {
        "scope": "seed",
        "challenge_id": "seed-one",
        "last_request": {"target_url": CHALLENGE},
    }
    args = ("http://api.example.test/api", status)
    if report == "notify_solver_blocked":
        args += ({"solver_cooldown_reason": "repeated_solver_failures"},)
    getattr(solver, report)(*args)
    assert same_auth_target("seed", requests[0]["target_url"], TARGET)
    assert "discarded" not in requests[0]["target_url"]


@pytest.mark.parametrize(
    "operation", ["rotate_failed_challenge_target", "rebuild_missing_challenge_target"]
)
def test_recreated_page_keeps_requested_region_sort_and_page(monkeypatch, operation):
    monkeypatch.setattr(
        pc2_solver_execution, "fetch_json", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        CaptchaSolver,
        "_open_target_tab",
        lambda self: {"id": "fresh", "url": self.target_url},
    )
    result = getattr(solver, operation)("http://127.0.0.1:9223", CHALLENGE)
    opened = result["probe_target"]["_target_url"]
    assert same_auth_target("seed", opened, TARGET)
    assert parse_qs(urlsplit(opened).query)["__captcha_solver_bg"] == ["1"]
    assert "discarded" not in opened


@pytest.mark.parametrize(
    "query", ["page=6", "location_code=110114", "st_param=5", "auction_start_seg=1"]
)
def test_distinct_list_jobs_do_not_share_a_target_route(query):
    key, value = query.split("=")
    old = parse_qs(urlsplit(TARGET).query)[key][0]
    different = TARGET.replace(f"{key}={old}", f"{key}={value}")
    probe = CaptchaSolver(target_url=TARGET)
    assert probe._solver_target_route(TARGET) != probe._solver_target_route(different)
    assert probe._solver_target_route(TARGET) == probe._solver_target_route(CHALLENGE)


def test_rebuild_does_not_reuse_a_healthy_page_from_another_region(monkeypatch):
    tab = {
        "id": "other-region",
        "type": "page",
        "url": TARGET.replace("120113", "110114"),
    }
    monkeypatch.setattr(
        pc2_solver_execution, "fetch_json", lambda *_args, **_kwargs: [tab]
    )
    monkeypatch.setattr(
        CaptchaSolver,
        "_open_target_tab",
        lambda self: {"id": "correct-region", "url": self.target_url},
    )
    result = solver.rebuild_missing_challenge_target("http://127.0.0.1:9223", TARGET)
    assert result["opened"]
    assert result["probe_target"]["_target_id"] == "correct-region"


def test_post_challenge_navigation_returns_to_the_original_list_request():
    probe = CaptchaSolver(target_url=TARGET)
    probe._send_cdp = lambda *_args, **_kwargs: {
        "result": {
            "value": "https://sf.taobao.com/list/200782003__2.htm/_____tmd_____/punish?x5secdata=discarded"
        }
    }
    assert same_auth_target("seed", probe._destination_list_url(), TARGET)


def test_challenge_probe_rejects_an_explicitly_different_list_identity(monkeypatch):
    tabs = [
        {
            "id": name,
            "type": "page",
            "url": url,
            "webSocketDebuggerUrl": "ws://localhost/" + name,
        }
        for name, url in [
            ("wrong", CHALLENGE.replace("120113", "110114")),
            ("correct", CHALLENGE),
        ]
    ]
    monkeypatch.setattr(pc2_solver_cdp, "fetch_json", lambda *_args, **_kwargs: tabs)
    result = solver.check_cdp_browser_for_challenge_page(
        "http://127.0.0.1:9223", TARGET
    )
    assert result["_target_id"] == "correct"


def test_unrelated_healthy_detail_page_is_not_seed_authentication(monkeypatch):
    monkeypatch.setattr(
        pc2_solver_cdp,
        "fetch_json",
        lambda *_args, **_kwargs: [
            {
                "id": "detail",
                "type": "page",
                "url": "https://sf-item.taobao.com/sf_item/123.htm",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/detail",
            }
        ],
    )
    monkeypatch.setattr(CaptchaSolver, "_connect_to_target", lambda *_args: True)
    monkeypatch.setattr(
        CaptchaSolver,
        "_page_challenge_summary",
        lambda _self: {"authenticatedPage": True},
    )
    assert (
        solver.check_cdp_browser_for_authenticated_target(
            "http://127.0.0.1:9223", TARGET
        )
        is None
    )
