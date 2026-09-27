from tools import pc2_solver_scope
from tools import pc2_solver_execution
from tools.test.pc2_local_solver_test_context import *


def test_manual_challenge_report_uses_canonical_taobao_target(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, payload, timeout):
        captured.update({"url": url, "payload": payload, "timeout": timeout})
        return {
            "status": "manual_required",
            "captcha_solver": {"challenge_id": "captcha-1"},
        }

    monkeypatch.setattr(pc2_solver_scope, "post_json", fake_post)
    result = pc2_local_solver.notify_manual_challenge(
        "http://192.168.15.200:8001/api",
        {
            "last_request": {
                "node_id": "pc2",
                "cdp_endpoint": "http://192.168.15.104:9224",
                "target_url": (
                    "https://sf-item.taobao.com//sf_item/747890132583.htm/_____tmd_____/punish"
                    "?x5secdata=secret"
                ),
            }
        },
        "pc2",
    )

    assert result["status"] == "manual_required"
    assert captured["url"] == "http://192.168.15.200:8001/api/report_manual_captcha"
    assert captured["timeout"] == 10
    assert captured["payload"] == {
        "target_url": "https://sf-item.taobao.com/sf_item/747890132583.htm",
        "url": "https://sf-item.taobao.com/sf_item/747890132583.htm",
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "manual_only": True,
        "timestamp": captured["payload"]["timestamp"],
    }


def test_rotate_failed_challenge_replaces_same_scope_duplicates_with_one_fresh_target(
    monkeypatch,
) -> None:
    closed: list[str] = []
    opened_urls: list[str] = []
    detail_challenge = (
        "https://sf-item.taobao.com/sf_item/747890132583.htm/_____tmd_____/punish"
        "?x5secdata=secret"
    )

    monkeypatch.setattr(
        pc2_solver_execution,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "detail-old-1",
                "type": "page",
                "title": "验证码拦截",
                "url": detail_challenge,
            },
            {
                "id": "detail-old-2",
                "type": "page",
                "title": "安全验证",
                "url": detail_challenge,
            },
            {
                "id": "detail-healthy",
                "type": "page",
                "title": "司法拍卖",
                "url": "https://sf-item.taobao.com/sf_item/123.htm",
            },
            {
                "id": "seed-challenge",
                "type": "page",
                "title": "验证码拦截",
                "url": "https://sf.taobao.com/list/1.htm/_____tmd_____/punish?x5secdata=secret",
            },
        ],
    )
    monkeypatch.setattr(
        pc2_local_solver.CaptchaSolver,
        "_close_cdp_target",
        lambda _self, target_id: closed.append(target_id) or True,
    )

    def fake_open(self):
        opened_urls.append(self.target_url)
        return {
            "id": "detail-fresh",
            "url": self.target_url,
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/detail-fresh",
        }

    monkeypatch.setattr(pc2_local_solver.CaptchaSolver, "_open_target_tab", fake_open)

    result = pc2_local_solver.rotate_failed_challenge_target(
        "http://127.0.0.1:9223",
        "https://sf-item.taobao.com//sf_item/747890132583.htm?token=discarded",
        {"_target_url": detail_challenge},
    )

    assert result["opened"] is True
    assert result["closed"] == 2
    assert result["scope"] == "detail"
    assert closed == ["detail-old-1", "detail-old-2"]
    assert opened_urls == [
        "https://sf-item.taobao.com/sf_item/747890132583.htm?__captcha_solver_bg=1"
    ]
    assert "secret" not in result["probe_target"]["_target_url"]
    assert "discarded" not in result["probe_target"]["_target_url"]


def test_rotate_failed_challenge_preserves_existing_login_window(monkeypatch) -> None:
    monkeypatch.setattr(
        pc2_solver_execution,
        "fetch_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("login window must be preserved without CDP tab rotation")
        ),
    )

    result = pc2_local_solver.rotate_failed_challenge_target(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/1.htm",
        {"_target_url": "https://login.taobao.com/member/login.jhtml"},
    )

    assert result == {
        "attempted": False,
        "opened": False,
        "closed": 0,
        "scope": "seed",
        "reason": "login_window_preserved",
    }


def test_rebuild_missing_challenge_target_opens_one_identity_first_canonical_target(
    monkeypatch,
) -> None:
    opened_urls: list[str] = []
    monkeypatch.setattr(
        pc2_solver_execution,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "keepalive",
                "type": "page",
                "url": "about:blank",
            },
            {
                "id": "other-detail",
                "type": "page",
                "url": "https://sf-item.taobao.com/sf_item/123.htm",
            },
        ],
    )

    def fake_open(self):
        opened_urls.append(self.target_url)
        return {
            "id": "detail-rebuilt",
            "url": self.target_url,
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/detail-rebuilt",
        }

    monkeypatch.setattr(pc2_local_solver.CaptchaSolver, "_open_target_tab", fake_open)

    result = pc2_local_solver.rebuild_missing_challenge_target(
        "http://127.0.0.1:9223",
        (
            "https://sf-item.taobao.com//sf_item/747890132583.htm/_____tmd_____/punish"
            "?x5secdata=discarded"
        ),
    )

    assert result["opened"] is True
    assert result["scope"] == "detail"
    assert result["reason"] == "missing_challenge_target_rebuilt"
    assert opened_urls == [
        "https://sf-item.taobao.com/sf_item/747890132583.htm?__captcha_solver_bg=1"
    ]
    assert "discarded" not in result["probe_target"]["_target_url"]


def test_rebuild_missing_challenge_target_reuses_matching_loading_route(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        pc2_solver_execution,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "detail-loading",
                "type": "page",
                "url": (
                    "https://sf-item.taobao.com/sf_item/747890132583.htm"
                    "?__captcha_solver_bg=1"
                ),
                "webSocketDebuggerUrl": (
                    "ws://127.0.0.1:9223/devtools/page/detail-loading"
                ),
            }
        ],
    )
    monkeypatch.setattr(
        pc2_local_solver.CaptchaSolver,
        "_open_target_tab",
        lambda _self: (_ for _ in ()).throw(
            AssertionError("matching route must not open a duplicate target")
        ),
    )

    result = pc2_local_solver.rebuild_missing_challenge_target(
        "http://127.0.0.1:9223",
        "https://sf-item.taobao.com/sf_item/747890132583.htm",
    )

    assert result["opened"] is False
    assert result["reason"] == "request_target_already_present"
    assert result["probe_target"]["_target_id"] == "detail-loading"


def test_solver_blocked_report_uses_canonical_target_and_challenge(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, payload, timeout):
        captured.update({"url": url, "payload": payload, "timeout": timeout})
        return {"status": "node_solver_blocked", "captcha_solver": {}}

    monkeypatch.setattr(pc2_solver_scope, "post_json", fake_post)
    result = pc2_local_solver.notify_solver_blocked(
        "http://192.168.15.200:8001/api",
        {
            "challenge_id": "captcha-detail",
            "scope": "detail",
            "last_request": {
                "node_id": "pc2",
                "cdp_endpoint": "http://192.168.15.104:9224",
                "target_url": (
                    "https://sf-item.taobao.com//sf_item/747890132583.htm/_____tmd_____/punish"
                    "?x5secdata=secret"
                ),
            },
        },
        {
            "scope": "detail",
            "slider_attempts": 10,
            "solver_cooldown_reason": "repeated_solver_failures",
        },
        "pc2",
    )

    assert result["status"] == "node_solver_blocked"
    assert captured["url"] == "http://192.168.15.200:8001/api/report_captcha"
    assert captured["timeout"] == 10
    assert captured["payload"] == {
        "target_url": "https://sf-item.taobao.com/sf_item/747890132583.htm",
        "url": "https://sf-item.taobao.com/sf_item/747890132583.htm",
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "challenge_id": "captcha-detail",
        "node_solver_blocked": True,
        "node_solver_blocked_reason": "repeated_solver_failures",
        "node_solver_blocked_attempts": 10,
        "timestamp": captured["payload"]["timestamp"],
        "scope": "detail",
    }


def test_manual_challenge_registration_repairs_legacy_pause_without_challenge_id() -> (
    None
):
    status = {
        "manual_only": True,
        "manual_required": True,
        "challenge_id": None,
        "last_request": {"target_url": "https://sf.taobao.com/list/50025969__2.htm"},
    }

    assert pc2_local_solver.manual_challenge_registration_needed(status) is True
    assert (
        pc2_local_solver.manual_challenge_registration_needed(
            {**status, "challenge_id": "captcha-current"}
        )
        is False
    )


def test_node_solver_execution_gate_requires_fresh_exclusive_ownership(
    monkeypatch,
) -> None:
    monkeypatch.delenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", raising=False)
    owned = {
        "running": False,
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
        },
    }

    assert (
        pc2_local_solver.node_solver_execution_block_reason(
            owned,
            "http://127.0.0.1:9223",
            "pc2",
        )
        is None
    )
    assert (
        pc2_local_solver.node_solver_execution_block_reason(
            {**owned, "running": True},
            "http://127.0.0.1:9223",
            "pc2",
        )
        == "nas_solver_running"
    )
    assert (
        pc2_local_solver.node_solver_execution_block_reason(
            {**owned, "manual_only": True},
            "http://127.0.0.1:9223",
            "pc2",
        )
        == "manual_only"
    )
    assert (
        pc2_local_solver.node_solver_execution_block_reason(
            {
                **owned,
                "manual_only": False,
                "last_request": {
                    **owned["last_request"],
                    "target_url": "https://sf.taobao.com/list/50025969__2.htm",
                },
            },
            "http://127.0.0.1:9223",
            "pc2",
        )
        == "manual_only"
    )
    assert (
        pc2_local_solver.node_solver_execution_block_reason(
            {"error": "status unavailable"},
            "http://127.0.0.1:9223",
            "pc2",
        )
        == "status_unavailable"
    )
    assert (
        pc2_local_solver.node_solver_execution_block_reason(
            {"running": False, "last_request": {"node_id": "pc3"}},
            "http://127.0.0.1:9223",
            "pc2",
        )
        == "request_owned_elsewhere"
    )


def test_node_solver_execution_gate_allows_explicit_real_taobao_auto_mode(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    owned = {
        "running": False,
        "manual_only": False,
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    }

    assert (
        pc2_local_solver.node_solver_execution_block_reason(
            owned,
            "http://127.0.0.1:9223",
            "pc2",
        )
        is None
    )
    assert (
        pc2_local_solver.node_solver_execution_block_reason(
            {**owned, "manual_only": True},
            "http://127.0.0.1:9223",
            "pc2",
        )
        == "manual_only"
    )


def test_completion_challenge_id_follows_same_owned_request_rotation(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    target_url = "https://sf.taobao.com/list/200782003__2.htm?__captcha_solver_bg=1"
    started = {
        "challenge_id": "captcha-old",
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": target_url,
        },
    }
    latest = {
        **started,
        "challenge_id": "captcha-current",
        "manual_only": False,
    }

    assert (
        pc2_local_solver._completion_challenge_id(
            started,
            latest,
            target_url,
            "http://127.0.0.1:9223",
            "pc2",
        )
        == "captcha-current"
    )


def test_completion_challenge_id_rejects_different_request_rotation(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    target_url = "https://sf.taobao.com/list/200782003__2.htm?__captcha_solver_bg=1"
    started = {
        "challenge_id": "captcha-old",
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": target_url,
        },
    }
    latest = {
        "challenge_id": "captcha-other",
        "manual_only": False,
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
        },
    }

    assert (
        pc2_local_solver._completion_challenge_id(
            started,
            latest,
            target_url,
            "http://127.0.0.1:9223",
            "pc2",
        )
        == "captcha-old"
    )


def test_manual_fallback_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED", raising=False)

    assert pc2_local_solver.manual_fallback_enabled() is False
    assert (
        pc2_local_solver._manual_fallback_latch_active(
            {"manual_pushed": True},
            manual_required=True,
        )
        is False
    )


def test_manual_fallback_latch_requires_explicit_enable(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED", "1")

    assert pc2_local_solver.manual_fallback_enabled() is True
    assert (
        pc2_local_solver._manual_fallback_latch_active(
            {"manual_pushed": True},
            manual_required=True,
        )
        is True
    )
    assert (
        pc2_local_solver._manual_fallback_latch_active(
            {"manual_pushed": True},
            manual_required=False,
        )
        is False
    )


def test_solver_cooldown_is_active_until_persisted_deadline(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "consecutive_failures": 3,
            "window_started_at": 900.0,
            "solver_cooldown_until": 1100.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )

    assert pc2_local_solver._solver_cooldown_active(state, now=1099.0) is True
    assert pc2_local_solver._solver_cooldown_active(state, now=1100.0) is False
    assert state["solver_cooldown_until"] == 1100.0
    assert state["solver_cooldown_reason"] == "repeated_solver_failures"
    assert state["consecutive_failures"] == 3
    assert state["window_started_at"] == 900.0
