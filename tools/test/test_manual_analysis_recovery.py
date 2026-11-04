"""Explicit reanalysis starts a bounded cycle without stealing a worker lease."""

from datetime import datetime, timedelta, timezone

import pytest

from src.storage.models import CollectionSeedItem
from tools.test import test_blocked_recovery as recovery_fixtures

repository = recovery_fixtures.repository


def seed(repo, **fields):
    with repo.session_factory.begin() as session:
        session.add(
            CollectionSeedItem(
                item_id="123",
                status="analysis_blocked",
                detail_last_error="model timeout",
                source_payload={
                    "_analysis_attempt_count": 3,
                    "_raw_detail_artifacts": {"detail_html_path": "/worker/raw.html"},
                },
                **fields,
            )
        )


def test_exhausted_manual_reanalysis_can_actually_be_claimed(repository):
    seed(repository)
    result = repository.requeue_seed_detail_analysis(
        "123", reason="retry after model recovery"
    )
    assert result["ok"] is True
    assert result["analysis_attempt_count"] == 0
    claim = repository.claim_seed_raw_detail_item("new-worker", max_analysis_attempts=3)
    assert claim["item_id"] == "123"
    with repository.session_factory() as session:
        payload = session.get(CollectionSeedItem, "123").source_payload
        assert payload["_analysis_attempt_count"] == 1
        assert payload["_manual_reanalysis_history"][0]["analysis_attempts"] == 3
        assert (
            payload["_manual_reanalysis_history"][0]["previous_error"]
            == "model timeout"
        )


@pytest.mark.parametrize(
    "until", [None, datetime.now(timezone.utc) + timedelta(days=1)]
)
def test_manual_reanalysis_preserves_active_or_unknown_lease(repository, until):
    seed(repository, detail_leased_by="owner", detail_lease_until=until)
    assert repository.requeue_seed_detail_analysis("123")["ok"] is False
    with repository.session_factory() as session:
        row = session.get(CollectionSeedItem, "123")
        assert row.status == "analysis_blocked"
        assert row.detail_leased_by == "owner"
        assert row.source_payload["_analysis_attempt_count"] == 3


def test_selected_json_alone_is_not_raw_input(repository):
    with repository.session_factory.begin() as session:
        session.add(
            CollectionSeedItem(
                item_id="123",
                status="analysis_blocked",
                selected_json_path="selected.json",
            )
        )
    assert repository.requeue_seed_detail_analysis("123")["ok"] is False


def test_expired_lease_is_recoverable_and_history_is_append_only(repository):
    seed(
        repository,
        detail_leased_by="old",
        detail_lease_until=datetime.now(timezone.utc) - timedelta(days=1),
    )
    assert repository.requeue_seed_detail_analysis("123", reason="first")["ok"]
    assert repository.requeue_seed_detail_analysis("123", reason="second")["ok"]
    with repository.session_factory() as session:
        row = session.get(CollectionSeedItem, "123")
        assert row.detail_leased_by is None
        assert [
            r["reason"] for r in row.source_payload["_manual_reanalysis_history"]
        ] == ["first", "second"]


def test_new_manual_cycle_still_stops_at_the_existing_attempt_limit(repository):
    seed(repository)
    assert repository.requeue_seed_detail_analysis("123")["ok"]
    for _ in range(3):
        assert repository.claim_seed_raw_detail_item("worker", max_analysis_attempts=3)
        repository.mark_seed_detail_analysis_failed("123", "still unavailable")
    assert (
        repository.claim_seed_raw_detail_item("worker", max_analysis_attempts=3) is None
    )
    with repository.session_factory() as session:
        row = session.get(CollectionSeedItem, "123")
        assert row.status == "analysis_blocked"
        assert row.source_payload["_analysis_attempt_count"] == 3
        assert (
            row.source_payload["_manual_reanalysis_history"][0]["analysis_attempts"]
            == 3
        )
