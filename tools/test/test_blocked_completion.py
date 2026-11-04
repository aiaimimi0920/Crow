"""AVM-unready final reports are complete; missing/partial evidence is not."""

import json

import pytest

from src.storage.blocked_recovery import requeue_blocked_items
from src.storage.models import (
    CollectionSeedItem,
    PropertyAudit,
    PropertyIngestEvent,
    PropertyListing,
)
from tools.test import test_blocked_recovery as recovery_fixtures

repository = recovery_fixtures.repository


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "bad_json",
        "wrong_id",
        "partial",
        "no_event",
        "wrong_path",
        "deleted",
        "module_b_partial",
        "bad_receipt",
    ],
)
def test_completion_uses_final_evidence_not_avm_readiness(
    repository, tmp_path, failure
):
    path = tmp_path / "final.json"
    payload = {
        "id": "123",
        "item_id": "123",
        "detail_captured": True,
        "is_processed": True,
    }
    if failure == "wrong_id":
        payload["id"] = "other"
    if failure == "partial":
        payload.pop("is_processed")
    path.write_text(
        "invalid" if failure == "bad_json" else json.dumps(payload), encoding="utf-8"
    )
    with repository.session_factory.begin() as session:
        session.add(
            CollectionSeedItem(
                item_id="123", status="analysis_blocked", final_json_path=str(path)
            )
        )
        session.add(
            PropertyListing(item_id="123", area_sqm=72, is_deleted=failure == "deleted")
        )
        session.add(
            PropertyAudit(
                item_id="123",
                is_processed=True,
                detail_captured=True,
                analysis_ready=False,
            )
        )
        if failure != "no_event":
            session.add(
                PropertyIngestEvent(
                    item_id="123",
                    event_type="detail_analysis_completed",
                    event_payload=["invalid"]
                    if failure == "bad_receipt"
                    else {
                        "item_id": "123",
                        "final_json_path": str(path)
                        if failure != "wrong_path"
                        else "wrong.json",
                        "analysis_module_b": {
                            "mode": "primary",
                            "status": "partial"
                            if failure == "module_b_partial"
                            else "finalized",
                        },
                    },
                )
            )
    result = requeue_blocked_items(
        repository, ["123"], recovery_id="reconcile", apply=True
    )[0]
    assert result.get("target_status") == (
        "detail_completed" if failure is None else None
    )
    if failure:
        assert result["skip"] == "processed_requires_review"
    with repository.session_factory() as session:
        assert session.get(PropertyListing, "123").area_sqm == 72
        assert session.get(PropertyAudit, "123").analysis_ready is False
