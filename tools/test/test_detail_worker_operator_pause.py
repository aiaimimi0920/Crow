"""Explicit operator pauses take priority over scope state and open pages."""

from types import SimpleNamespace

import pytest

from tools import detail_worker, detail_worker_execution, detail_worker_policy


def paused_status(signal, layout):
    status = {
        "paused": True,
        "captcha_solver": {
            "paused": True,
            "manual_required": False,
            "running": False,
            "last_request": {
                "target_url": "https://sf-item.taobao.com/sf_item/3001.htm"
            },
        },
    }
    if signal == "operator_paused":
        status["operator_paused"] = True
    else:
        status["captcha_solver"]["pause_reason"] = "operator"
    scopes = {
        "seed": {"paused": True, "manual_required": True},
        "detail": {"paused": False, "manual_required": False, "challenge_id": None},
    }
    if layout == "top":
        status["collection_scopes"] = scopes
    else:
        status["captcha_solver"][layout] = scopes
    return status


@pytest.mark.parametrize("owner", [detail_worker_execution, detail_worker])
@pytest.mark.parametrize("signal", ["operator_paused", "pause_reason"])
@pytest.mark.parametrize("layout", ["top", "collection_scopes", "scopes"])
def test_operator_pause_prevents_claim_even_with_open_page(
    tmp_path, monkeypatch, owner, signal, layout
):
    payload = paused_status(signal, layout)
    monkeypatch.setattr(
        owner,
        "_collection_pause_state_with_retry",
        lambda _base: detail_worker_policy._normalize_collection_pause_state(payload),
        raising=False,
    )
    if owner is detail_worker_execution:
        for name in (
            "_pause_state_has_resolved_open_detail_page",
            "_write_runtime_summary",
        ):
            monkeypatch.setattr(
                owner, name, getattr(detail_worker_policy, name), raising=False
            )

    def unexpected(*_args, **_kwargs):
        pytest.fail("operator pause must prevent claiming or processing an item")

    repo = SimpleNamespace(
        seed_queue_counts=dict,
        claim_seed_detail_item=unexpected,
    )
    result = owner.run_detail_worker_once(
        owner.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="",
            api_base_url="https://example.invalid/api",
            target_success=1,
            max_attempts=1,
            worker_id="test-detail",
            do_risk=False,
        ),
        repository=repo,
        http_session=None,
        browser_pages={
            "3001": (
                "<html><body>detail</body></html>",
                "https://sf-item.taobao.com/sf_item/3001.htm",
            )
        },
        process_item_func=unexpected,
    )
    assert result["decision"] == "detail_collection_paused"
    assert result["reason"] == "operator_paused"


@pytest.mark.parametrize("signal", ["operator_paused", "pause_reason"])
def test_operator_pause_does_not_early_wake_auth_backoff(monkeypatch, signal):
    from tools import detail_worker_wait as owner

    clock = {"now": 0}
    monkeypatch.setattr(owner.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _stage: True)
    monkeypatch.setattr(
        owner.worker_lifecycle,
        "wait",
        lambda seconds: clock.update(now=clock["now"] + seconds),
    )
    monkeypatch.setattr(
        owner, "fetch_json", lambda *_args, **_kwargs: paused_status(signal, "top")
    )
    owner.wait_after_detail_batch(
        SimpleNamespace(
            analysis_only=False, api_base_url="https://example.invalid/api"
        ),
        {"results": [{"decision": "detail_collection_paused"}]},
        900,
    )
    assert clock["now"] == 900


def test_stale_operator_reason_without_active_pause_does_not_block_detail():
    status = paused_status("pause_reason", "top")
    status["paused"] = False
    status["captcha_solver"]["paused"] = False
    status["collection_scopes"]["seed"]["paused"] = False
    result = detail_worker_policy._normalize_collection_pause_state(status)
    assert result["paused"] is False
