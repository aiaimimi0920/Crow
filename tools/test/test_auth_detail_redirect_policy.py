"""Redirect transport authorization is narrower than canonical item identity."""

import json
from threading import Event
from types import SimpleNamespace

import pytest

from src.auth_cookie_probe_budget import snapshot_probe_budget
from src.collection.adapters import taobao_detail_auth as detail

TARGET = "https://sf-item.taobao.com/sf_item/123.htm"
ALIAS = "https://susong-item.taobao.com/auction/123.htm"
READY = '<div id="J_StartPrice">100</div>'
SECRET = "synthetic-redirect-secret"


def probe(
    monkeypatch,
    location=ALIAS,
    *,
    limit=3,
    status=302,
    final=None,
    first_seconds=0,
    second_seconds=0,
    stop=None,
    scoped=True,
    enabled=True,
):
    calls = []
    clock = [100.0]
    monkeypatch.setattr(detail, "monotonic", lambda: clock[0])

    def get(url, **options):
        calls.append((url, options))
        if len(calls) == 1:
            clock[0] += first_seconds
            if stop is not None:
                stop.set()
            return SimpleNamespace(
                status_code=status,
                url=TARGET,
                text=READY,
                headers={"Location": location},
            )
        assert len(calls) == 2
        clock[0] += second_seconds
        return final or SimpleNamespace(
            status_code=200, url=ALIAS, text=READY, headers={}
        )

    with snapshot_probe_budget("detail" if scoped else None, limit, stop) as budget:
        result = detail.probe_detail_page(
            TARGET,
            cookies=[],
            session=SimpleNamespace(get=get),
            timeout=15,
            user_agent="synthetic-UA",
            allow_same_detail_redirect=enabled,
        )
        assert budget is None or budget.used == len(calls)
    assert all(options["allow_redirects"] is False for _, options in calls)
    assert SECRET not in json.dumps(result)
    return result, calls


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_only_exact_allowlisted_same_item_can_reach_payload(monkeypatch, status):
    result, calls = probe(monkeypatch, status=status)
    assert result["healthy"] is True
    assert result["same_detail_redirect_followed"] is True
    assert result["http_request_count"] == 2
    assert result["final_url"] == TARGET
    assert [url for url, _ in calls] == [TARGET, ALIAS]
    assert calls[1][1]["headers"]["Referer"] == TARGET


@pytest.mark.parametrize(
    "location",
    [
        TARGET,
        "https://SF-ITEM.TAOBAO.COM:443/sf_item/123.htm",
        "/sf_item/123.htm",
        ALIAS + "?",
        ALIAS + "#",
        ALIAS + f"?trace={SECRET}",
        ALIAS + "?x5sec=",
        ALIAS + "?%785sec",
        ALIAS + "?X5SECDATA=",
        ALIAS + "?x5sec=&x5sec=",
        ALIAS + f"#ticket={SECRET}",
        "https://susong-item.taobao.com/auction/456.htm",
        "https://login.taobao.com/",
        "https://sf-item.taobao.com/_____tmd_____/punish",
        "https://sf-item.taobao.com/sf_item/123.htm/_____tmd_____/slide",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://169.254.169.254/",
        "https://taobao.com.example.invalid/auction/123.htm",
        "https://other.taobao.com/auction/123.htm",
        "http://susong-item.taobao.com/auction/123.htm",
        "https://susong-item.taobao.com:9443/auction/123.htm",
        "https://user@susong-item.taobao.com/auction/123.htm",
        "https://susong-item.taobao.com./auction/123.htm",
        "https://susong-item.taobao.com/auction/123.htm\r\nCookie: synthetic",
        "https://susong-item.taobao.com\\@example.invalid/auction/123.htm",
    ],
)
def test_query_self_login_challenge_other_item_and_untrusted_targets_never_follow(
    monkeypatch, location
):
    result, calls = probe(monkeypatch, location)
    assert result["healthy"] is False and len(calls) == 1


@pytest.mark.parametrize(
    "options",
    [
        {"scoped": False},
        {"enabled": False},
        {"limit": 1},
        {"first_seconds": 15},
    ],
)
def test_no_authority_no_slot_or_expired_budget_never_sends_second_request(
    monkeypatch, options
):
    result, calls = probe(monkeypatch, **options)
    assert result["healthy"] is False and len(calls) == 1


def test_remaining_timeout_not_full_timeout_is_passed_to_second_get(monkeypatch):
    result, calls = probe(monkeypatch, first_seconds=10)
    assert result["healthy"] is True
    assert calls[0][1]["timeout"] == 15 and calls[1][1]["timeout"] == 5


def test_late_response_cannot_become_auth_proof(monkeypatch):
    result, calls = probe(monkeypatch, first_seconds=10, second_seconds=5)
    assert result["healthy"] is False and len(calls) == 2


def test_stopping_after_first_response_prevents_new_get(monkeypatch):
    stop = Event()
    result, calls = probe(monkeypatch, stop=stop)
    assert stop.is_set() and result["healthy"] is False and len(calls) == 1


def test_second_response_relative_redirect_uses_its_actual_origin(monkeypatch):
    final = SimpleNamespace(
        status_code=302,
        url=ALIAS,
        text="",
        headers={"Location": "/auction/123.htm"},
    )
    result, calls = probe(monkeypatch, final=final)
    assert result["redirect_kind"] == "same_detail"
    assert result["healthy"] is False and len(calls) == 2


@pytest.mark.parametrize(
    "status,url,text,headers",
    [
        (302, ALIAS, READY, {"Location": TARGET}),
        (302, ALIAS, READY, {"Location": "https://127.0.0.1/"}),
        (200, ALIAS, READY + "扫码登录", {}),
        (200, ALIAS, READY + "请完成验证", {}),
        (200, ALIAS, "", {}),
        (200, TARGET, READY, {}),
        (200, ALIAS.replace("123", "456"), READY, {}),
        (200, ALIAS + f"?trace={SECRET}", READY, {}),
        (200, ALIAS + "?x5sec=", READY, {}),
        (403, ALIAS, READY, {}),
    ],
)
def test_second_redirect_or_invalid_final_payload_never_becomes_proof(
    monkeypatch, status, url, text, headers
):
    final = SimpleNamespace(status_code=status, url=url, text=text, headers=headers)
    result, calls = probe(monkeypatch, final=final)
    assert result["healthy"] is False and len(calls) == 2
