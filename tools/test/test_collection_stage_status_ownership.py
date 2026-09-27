"""Collection status keeps storage modes, audit order, and hybrid projections."""

import json
from types import SimpleNamespace

import pytest

from src import manual_review_status
from src.storage.repository import DatabaseSettings, PropertyRepository


@pytest.fixture(params=["native", "facade"])
def stage_snapshot(request, monkeypatch):
    if request.param == "native":
        from src import server_manual_review as owner
    else:
        from src import server as owner

    def snapshot(data_root, repository):
        if request.param == "native":
            return owner._db_collection_stage_snapshot(data_root, repository=repository)
        monkeypatch.setattr(owner, "DATA_DIR", str(data_root))
        monkeypatch.setattr(owner, "DB_REPOSITORY", repository)
        return owner._db_collection_stage_snapshot()

    return snapshot


@pytest.fixture
def repository():
    repo = PropertyRepository(
        DatabaseSettings(
            url="sqlite:///:memory:",
            enabled=True,
            auto_create=True,
            echo=False,
            enable_postgis=False,
        )
    )
    repo.initialize()
    yield repo
    repo.engine.dispose()


def test_disabled_database_keeps_hybrid_projection_and_records_once(
    tmp_path, stage_snapshot, monkeypatch
):
    avm = tmp_path / "avm"
    avm.mkdir()
    source = avm / "hybrid_seed_collection_runtime.json"
    raw = json.dumps(
        {
            "last_decision": "browser_fallback_required",
            "last_reason": "challenge_detected",
            "browser_fallback_required_count": 3,
        }
    ).encode("utf-8")
    source.write_bytes(raw)
    calls = []
    original = manual_review_status.record_manual_review_control_plane_integrity

    def record(data_root, integrity):
        calls.append(data_root)
        return original(data_root, integrity)

    monkeypatch.setattr(
        manual_review_status, "record_manual_review_control_plane_integrity", record
    )
    result = stage_snapshot(tmp_path, SimpleNamespace(enabled=False))
    assert result["seed_stage"] == {}
    assert result["detail_stage"] == {}
    assert result["analysis_stage"] == {}
    assert result["search_tasks"] == {}
    assert (
        result["hybrid_collection_runtime_summary"]["last_reason"]
        == "challenge_detected"
    )
    assert (
        result["operator_overview"]["hybrid_collection_last_reason"]
        == "challenge_detected"
    )
    assert (
        result["operator_overview"]["hybrid_collection_last_decision"]
        == "browser_fallback_required"
    )
    assert calls == [tmp_path]
    assert source.read_bytes() == raw


def test_enabled_database_preserves_stage_and_search_counts(
    tmp_path, repository, monkeypatch, stage_snapshot
):
    monkeypatch.setattr(
        repository,
        "stage_status_counts",
        lambda: {
            "seed_stored": 7,
            "detail_pending": 3,
            "analysis_ready": 2,
        },
    )
    monkeypatch.setattr(repository, "search_task_counts", lambda: {"search_pending": 4})
    monkeypatch.setattr(
        repository,
        "analysis_readiness_snapshot",
        lambda: {
            "blockers": {"detail_stage": 3},
        },
    )
    result = stage_snapshot(tmp_path, repository)
    assert result["seed_stage"] == {"stored": 7}
    assert result["detail_stage"]["pending"] == 3
    assert result["detail_stage"]["failed"] == 0
    assert result["analysis_stage"] == {"ready": 2, "not_ready": 0, "invalid": 0}
    assert result["search_tasks"] == {"search_pending": 4}
    assert result["analysis_blockers"] == {"detail_stage": 3}
    assert result["manual_review_control_plane_storage"]["state_source"] == "repository"


@pytest.mark.parametrize(
    "failure",
    [
        "stage_status_counts",
        "search_task_counts",
        "analysis_readiness_snapshot",
    ],
)
def test_count_failure_keeps_control_plane_and_discards_partial_counts(
    tmp_path, repository, monkeypatch, stage_snapshot, failure
):
    monkeypatch.setattr(repository, "stage_status_counts", lambda: {"seed_stored": 7})
    monkeypatch.setattr(repository, "search_task_counts", lambda: {"search_pending": 4})

    def fail():
        raise RuntimeError("count query unavailable")

    monkeypatch.setattr(repository, failure, fail)
    result = stage_snapshot(tmp_path, repository)
    assert result["seed_stage"] == {"stored": 0}
    assert result["search_tasks"] == {}
    assert result["analysis_blockers"] == {}
    assert result["manual_review_control_plane_storage"]["state_source"] == "repository"
    assert "recommended_actions" in result
    assert "hybrid_collection_runtime_summary" in result
