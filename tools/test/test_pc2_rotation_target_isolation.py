"""Failure rotation must not close another worker's collection target."""

import pytest

from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_execution as execution

DETAIL = "https://sf-item.taobao.com/sf_item/101.htm"
SEED = "https://sf.taobao.com/list/1.htm?location_code=120113&page=5&st_param=4"


def challenge(url):
    path, _, query = url.partition("?")
    return path + "/_____tmd_____/punish?" + query + "&x5secdata=private"


def rotate(monkeypatch, target, tabs, **kwargs):
    closed = []
    opened = []
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: tabs)
    monkeypatch.setattr(
        CaptchaSolver,
        "_close_cdp_target",
        lambda _s, value: closed.append(value) or True,
    )

    def open_target(solver):
        opened.append(solver.target_url)
        return {"id": "fresh", "url": solver.target_url}

    monkeypatch.setattr(CaptchaSolver, "_open_target_tab", open_target)
    result = execution.rotate_failed_challenge_target(
        "http://fixture", target, **kwargs
    )
    return closed, opened, result


def page(identity, url, **extra):
    return {"id": identity, "type": "page", "url": url, "title": "安全验证", **extra}


@pytest.mark.parametrize(
    "other",
    [
        DETAIL.replace("101.htm", "102.htm"),
        DETAIL.replace("sf-item.taobao.com", "susong-item.taobao.com"),
        DETAIL.replace("sf-item.taobao.com", "unrelated.example.test"),
    ],
)
def test_detail_rotation_preserves_another_item_or_source(monkeypatch, other):
    closed, opened, result = rotate(
        monkeypatch,
        DETAIL,
        [page("requested", challenge(DETAIL)), page("other", challenge(other))],
    )
    assert closed == ["requested"]
    assert len(opened) == 1
    assert result["closed"] == 1
    assert result["opened"] is True


@pytest.mark.parametrize(
    "other",
    [
        SEED.replace("120113", "110114"),
        SEED.replace("page=5", "page=6"),
        SEED.replace("st_param=4", "st_param=5"),
        SEED.split("?")[0],
        SEED.replace("/list/1.htm", "/list/2.htm"),
    ],
)
def test_seed_rotation_preserves_distinct_or_unbound_list_jobs(monkeypatch, other):
    closed, opened, result = rotate(
        monkeypatch,
        SEED,
        [page("requested", challenge(SEED)), page("other", challenge(other))],
    )
    assert closed == ["requested"]
    assert len(opened) == 1
    assert result["closed"] == 1


@pytest.mark.parametrize("target", [DETAIL, SEED])
def test_same_target_duplicates_still_rotate_once(monkeypatch, target):
    equivalent = challenge(target) + "&spm=tracking&__captcha_solver_bg=1"
    closed, opened, result = rotate(
        monkeypatch,
        target,
        [page("first", challenge(target)), page("second", equivalent)],
    )
    assert closed == ["first", "second"]
    assert result["closed"] == 2
    assert len(opened) == 1
    assert "x5secdata" not in opened[0]
    assert "private" not in repr(result)


@pytest.mark.parametrize("target", [DETAIL, SEED])
def test_rotation_preserves_login_healthy_unknown_and_other_scope(monkeypatch, target):
    other_scope = SEED if target == DETAIL else DETAIL
    closed, opened, result = rotate(
        monkeypatch,
        target,
        [
            page("requested", challenge(target)),
            page("login", "https://login.taobao.com/member/login.jhtml"),
            page("healthy", target, title="司法拍卖"),
            page("other-scope", challenge(other_scope)),
            page("blank", "about:blank"),
            page("unknown", ""),
            page("iframe", challenge(target), type="iframe"),
        ],
    )
    assert closed == ["requested"]
    assert len(opened) == 1
    assert result["closed"] == 1


def test_unrelated_challenges_are_retained_when_requested_page_is_missing(monkeypatch):
    closed, opened, result = rotate(
        monkeypatch,
        DETAIL,
        [page("other", challenge(DETAIL.replace("101.htm", "102.htm")))],
    )
    assert closed == []
    assert len(opened) == 1
    assert result["closed"] == 0
    assert result["opened"] is True


@pytest.mark.parametrize("target", [DETAIL, SEED])
def test_cooldown_closes_only_rejected_request_without_preloading(monkeypatch, target):
    other = target.replace("101.htm", "102.htm") if target == DETAIL else DETAIL
    closed, opened, result = rotate(
        monkeypatch,
        target,
        [
            page("rejected", challenge(target)),
            page("other", challenge(other)),
            page("login", "https://login.taobao.com/member/login.jhtml"),
            page("healthy", target, title="司法拍卖"),
        ],
        open_replacement=False,
    )
    assert closed == ["rejected"]
    assert opened == []
    assert result == {
        "attempted": True,
        "opened": False,
        "closed": 1,
        "scope": "detail" if target == DETAIL else "seed",
        "reason": "rejected_challenge_closed_for_cooldown",
    }


@pytest.mark.parametrize("keepalive", ["blank", None])
def test_cooldown_never_closes_last_page_without_keepalive(monkeypatch, keepalive):
    from unittest.mock import Mock

    keeper = Mock(return_value=keepalive)
    monkeypatch.setattr(CaptchaSolver, "_open_keepalive_tab", keeper)
    closed, opened, result = rotate(
        monkeypatch,
        DETAIL,
        [page("rejected", challenge(DETAIL))],
        open_replacement=False,
    )
    keeper.assert_called_once_with()
    assert closed == (["rejected"] if keepalive else [])
    assert opened == []
    assert result["closed"] == bool(keepalive)
    assert result["opened"] is False


def test_cooldown_missing_request_does_not_create_any_page(monkeypatch):
    from unittest.mock import Mock

    keeper = Mock()
    monkeypatch.setattr(CaptchaSolver, "_open_keepalive_tab", keeper)
    closed, opened, result = rotate(monkeypatch, DETAIL, [], open_replacement=False)
    assert closed == opened == []
    assert result["closed"] == 0
    assert result["opened"] is False
    keeper.assert_not_called()


def test_cooldown_preserves_queryless_seed_challenge_without_identity(monkeypatch):
    closed, opened, result = rotate(
        monkeypatch,
        SEED,
        [page("unbound", challenge(SEED.split("?")[0]))],
        open_replacement=False,
    )
    assert closed == opened == []
    assert result["closed"] == 0
    assert result["opened"] is False
