"""Browser capacity is shared backpressure, not a bad item or auth failure."""

import json

import pytest

from src.storage.models import FapaiSeedItem
from tools import detail_worker, detail_worker_wait
from tools.cdp_background_page import BackgroundPageCapacityError
from tools.detail_browser_capture import decode_capture_reply
from tools.detail_browser_capture_child import capture_reply
from tools.test.test_detail_capture_diagnostics import worker_failure


def test_capacity_survives_private_child_protocol_without_private_text():
    def capture(*a, **k):
        raise BackgroundPageCapacityError("SECRET http://private")

    reply = capture_reply(capture, {"seed": {}, "cdp_endpoint": "http://fixture"})
    assert reply == {"kind": "capacity"}
    with pytest.raises(BackgroundPageCapacityError) as error:
        decode_capture_reply(json.dumps(reply), cdp_endpoint="http://fixture")
    assert "SECRET" not in str(error.value)


def test_capacity_preserves_item_and_breaks_batch_without_solver_or_health(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *a, **k: pytest.fail("capacity is not auth"),
    )
    monkeypatch.setattr(
        detail_worker,
        "_build_cdp_unreachable_health",
        lambda *a: pytest.fail("capacity is not outage"),
    )
    summary, repository = worker_failure(
        tmp_path, BackgroundPageCapacityError("SECRET")
    )
    try:
        assert summary["reason"] == "detail_browser_page_capacity"
        assert summary["retry_budget_preserved"] is True
        assert "SECRET" not in json.dumps(summary)
        with repository.session_factory() as session:
            row = session.get(FapaiSeedItem, "3001")
            assert row.status == "pending_detail" and row.detail_attempt_count == 0
        config = detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            challenge_cooldown_seconds=60,
            cdp_endpoint="http://fixture",
            target_success=1,
            max_attempts=1,
            worker_id="capacity-test",
            do_risk=False,
        )
        assert detail_worker._detail_challenge_should_break_batch(config, summary)
        assert (
            detail_worker._detail_challenge_retry_after_seconds(config, summary) == 60
        )
    finally:
        repository.engine.dispose()


def test_capacity_wait_uses_normal_cancelable_backoff_not_auth_polling(
    tmp_path, monkeypatch
):
    waits = []
    monkeypatch.setattr(detail_worker_wait.worker_lifecycle, "wait", waits.append)
    monkeypatch.setattr(
        detail_worker_wait, "fetch_json", lambda *a, **k: pytest.fail("no auth polling")
    )
    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        api_base_url="http://fixture",
        cdp_endpoint="http://fixture",
        target_success=1,
        max_attempts=1,
        worker_id="capacity-test",
        do_risk=False,
    )
    detail_worker_wait.wait_after_detail_batch(
        config, {"results": [{"reason": "detail_browser_page_capacity"}]}, 60
    )
    assert waits == [60]


def test_capacity_ends_real_batch_before_claiming_another_item(tmp_path, monkeypatch):
    from tools.test.detail_worker_test_context import _make_repo, _seed_one_item

    repository = _make_repo(tmp_path)
    _seed_one_item(repository)
    calls = []
    monkeypatch.setattr(
        detail_worker, "_collection_pause_state_with_retry", lambda _: {}
    )
    monkeypatch.setattr("tools.worker_lifecycle.checkpoint", lambda _: True)

    def process(*args, **kwargs):
        calls.append(True)
        raise BackgroundPageCapacityError("capacity")

    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://fixture",
        target_success=3,
        max_attempts=3,
        worker_id="capacity-batch",
        do_risk=False,
        llm_preflight_enabled=False,
        challenge_cooldown_seconds=60,
    )
    try:
        result = detail_worker.run_detail_worker_batch(
            config,
            repository=repository,
            http_session=object(),
            browser_pages={},
            process_item_func=process,
        )
        assert calls == [True] and result["attempts"] == 1
        assert result["challenge_break"] is True and result["retry_after_seconds"] == 60
    finally:
        repository.engine.dispose()
