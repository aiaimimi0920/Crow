"""Regression cases for the independent collection repair audit."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.collection.detail_failures import DetailFailures, input_version
from src.collection.detail_service import DetailCollectionService


def repository(count):
    rows = [{"id": str(i), "url": f"https://example.invalid/{i}"} for i in range(count)]

    def query(limit, offset=0):
        return rows[offset : offset + limit]

    return SimpleNamespace(
        enabled=True,
        iter_pending_task_items=query,
        iter_pending_flat_items=query,
        counts_snapshot=lambda: {"db_total_ids": count, "db_pending_ids": count},
    )


@pytest.mark.parametrize("batch", [False, True])
def test_dispatch_reaches_beyond_cooling_prefix(tmp_path, batch):
    service = DetailCollectionService(tmp_path, repository=repository(101))
    dispatched = {str(i): datetime.now(timezone.utc) for i in range(100)}
    if batch:
        result = service.batch_tasks(
            dispatched_tasks=dispatched, cooldown_seconds=600, batch_size=1
        )
        assert result["tasks"] == [{"id": "100", "url": "https://example.invalid/100"}]
    else:
        assert service.next_task(dispatched, 600) == {
            "url": "https://example.invalid/100"
        }


def test_visit_reaches_beyond_existing_capture_prefix(tmp_path):
    service = DetailCollectionService(tmp_path, repository=repository(501))
    for index in range(500):
        (tmp_path / f"item-{index}.html").touch()
    result = service.next_visit_task(dispatched_tasks={}, cooldown_seconds=600)
    assert result["id"] == "500"


def test_legacy_visit_respects_rejection_and_explicit_replay(tmp_path):
    service = DetailCollectionService(tmp_path)
    data = {
        "id": "1",
        "url": "https://example.invalid/1",
        "detail_fetch_status": "detail_rejected",
    }
    options = {
        "dispatched_tasks": {},
        "cooldown_seconds": 600,
        "legacy_entries": [("1", {"data": data})],
    }
    assert service.next_visit_task(**options) == {"task_type": "none"}
    data["detail_replay_requested_at"] = "2026-11-15"
    assert service.next_visit_task(**options)["id"] == "1"


@pytest.mark.parametrize(
    "damage", ["json", "shape", "attempts", "exhausted", "retry_at", "nan", "version"]
)
def test_corrupt_receipt_blocks_without_resetting_budget(tmp_path, damage, caplog):
    path = tmp_path / "item-1.html"
    path.write_text("capture", encoding="utf-8")
    failures = DetailFailures(tmp_path)
    failures.record("1", input_version(path), "extraction", ValueError())
    receipt = failures.path("1")
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    if damage == "shape":
        payload = []
    elif damage == "nan":
        payload["retry_at"] = float("nan")
    elif damage == "version":
        payload["input_version"] = [True, 0]
    elif damage != "json":
        payload[damage] = "invalid"
    receipt.write_text(
        "{" if damage == "json" else json.dumps(payload), encoding="utf-8"
    )
    before = receipt.read_bytes()
    assert failures.ready(str(path)) is False
    assert "Detail retry blocked" in caplog.text
    failures.record("1", input_version(path), "extraction", ValueError())
    assert "preserved for repair" in caplog.text
    assert receipt.read_bytes() == before
