"""Completion requires a matching, persisted final artifact in both worker paths."""

from unittest.mock import Mock

import pytest

from tools import detail_worker


@pytest.fixture
def worker(tmp_path):
    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        worker_id="integrity-fixture",
        target_success=1,
        max_attempts=1,
        do_risk=False,
    )
    repository = Mock()
    repository.claim_seed_detail_item.return_value = {
        "item_id": "123",
        "url": "https://sf-item.taobao.com/sf_item/123.htm",
    }
    repository.claim_seed_raw_detail_item.return_value = {"item_id": "123"}
    repository.seed_queue_counts.return_value = {}
    return config, repository


def execute(worker, monkeypatch, stage, artifact):
    config, repository = worker
    monkeypatch.setattr(
        detail_worker, "_collection_pause_state_with_retry", lambda *_: {}
    )
    monkeypatch.setattr(
        detail_worker, "_stage_raw_detail_artifacts_for_analysis", lambda *a, **k: {}
    )

    processed = []

    def process(*_args, **_kwargs):
        processed.append(True)
        if artifact is not None:
            folder = config.output_dir / "123"
            folder.mkdir(exist_ok=True)
            (folder / "final.json").write_bytes(artifact)
        return {}

    if stage == "analysis":
        result = detail_worker.run_detail_analysis_once(
            config,
            repository=repository,
            analyze_item_func=process,
        )
    else:
        result = detail_worker.run_detail_worker_once(
            config,
            repository=repository,
            http_session=None,
            browser_pages={},
            process_item_func=process,
        )
    assert processed == [True]
    return result


@pytest.mark.parametrize("stage", ["analysis", "detail"])
@pytest.mark.parametrize(
    "artifact",
    [
        None,
        b"not-json",
        b"\xff",
        b"[]",
        b"{}",
        b'{"price":1}',
        b'{"id":"other"}',
        b'{"id":"123","item_id":"other"}',
    ],
)
def test_invalid_final_artifact_never_completes(worker, monkeypatch, stage, artifact):
    result = execute(worker, monkeypatch, stage, artifact)
    repository = worker[1]
    assert result["decision"].endswith("retryable_failure")
    repository.upsert_flat_item.assert_not_called()
    repository.mark_seed_detail_completed.assert_not_called()


@pytest.mark.parametrize("stage", ["analysis", "detail"])
@pytest.mark.parametrize(
    "artifact", [b'{"id":"123"}', b'{"id":123}', b'{"item_id":"123"}']
)
def test_matching_artifact_persists_before_completion(
    worker, monkeypatch, stage, artifact
):
    result = execute(worker, monkeypatch, stage, artifact)
    repository = worker[1]
    assert result["decision"].endswith("completed")
    calls = [call[0] for call in repository.mock_calls]
    assert calls.index("upsert_flat_item") < calls.index("mark_seed_detail_completed")


@pytest.mark.parametrize("stage", ["analysis", "detail"])
def test_persistence_failure_never_completes(worker, monkeypatch, stage):
    repository = worker[1]
    repository.upsert_flat_item.side_effect = RuntimeError(
        "synthetic persistence failure"
    )
    result = execute(worker, monkeypatch, stage, b'{"id":"123"}')
    assert result["decision"].endswith("retryable_failure")
    repository.mark_seed_detail_completed.assert_not_called()
