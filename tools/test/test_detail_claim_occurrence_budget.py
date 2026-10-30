"""Detail claims read one source occurrence without dropping its history."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, insert, select
from sqlalchemy.dialects import postgresql

from src.storage.models import CollectionSeedItem, CollectionSeedOccurrence
from src.storage.repository import DatabaseSettings, PropertyRepository


@pytest.fixture
def queue(tmp_path):
    repo = PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'queue.sqlite3').as_posix()}",
            enabled=True,
            auto_create=True,
            enable_postgis=False,
        )
    )
    repo.initialize()
    yield repo
    repo.engine.dispose()


def populate(repo, count, payload):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with repo.session_factory.begin() as session:
        session.add_all(
            [
                CollectionSeedItem(
                    item_id="1001", status="pending_detail", source_payload=payload
                ),
                CollectionSeedItem(
                    item_id="1002",
                    status="in_progress",
                    detail_leased_by="other-worker",
                    detail_lease_until=datetime(2099, 1, 1, tzinfo=timezone.utc),
                ),
            ]
        )
        session.flush()
        if count:
            session.execute(
                insert(CollectionSeedOccurrence),
                [
                    {
                        "id": index + 1,
                        "occurrence_key": f"occurrence-{index}",
                        "item_id": "1001",
                        "job_key": "job",
                        "progress_key": "job:sort",
                        "sort_key": f"sort-{index}",
                        "sort_name": f"Sort {index}",
                        "st_param": str(index),
                        "page": index + 1,
                        "source_page_url": f"https://example.test/list?page={index + 1}",
                        # Same earliest timestamp exercises the id tie-breaker.
                        "seen_at": now + timedelta(seconds=max(index - 1, 0)),
                    }
                    for index in reversed(range(count))
                ],
            )


@pytest.mark.parametrize("count", [0, 1, 257])
def test_detail_claim_materializes_at_most_one_occurrence(queue, count):
    populate(queue, count, {})
    loaded, statements = [], []

    def on_load(_session, row):
        if isinstance(row, CollectionSeedOccurrence):
            loaded.append(row.id)

    def on_execute(state):
        if state.is_select and any(
            table.name == CollectionSeedOccurrence.__tablename__
            for table in state.statement.get_final_froms()
        ):
            statements.append(state.statement)

    event.listen(queue.session_factory, "loaded_as_persistent", on_load)
    event.listen(queue.session_factory, "do_orm_execute", on_execute)
    try:
        claim = queue.claim_seed_detail_item("detail-worker", lease_seconds=30)
    finally:
        event.remove(queue.session_factory, "loaded_as_persistent", on_load)
        event.remove(queue.session_factory, "do_orm_execute", on_execute)

    assert claim["item_id"] == "1001"
    assert loaded == ([1] if count else [])
    assert len(statements) == 1
    sql = str(
        statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "LIMIT 1" in sql
    assert "seen_at ASC" in sql and "id ASC" in sql
    if count:
        assert claim["source_page_url"] == "https://example.test/list?page=1"
        assert claim["list_page"] == 1
        assert claim["list_st_param"] == "0"
        assert claim["list_sort_key"] == "sort-0"
        assert claim["list_sort_name"] == "Sort 0"
    else:
        assert "source_page_url" not in claim
    with queue.session_factory() as session:
        assert session.scalar(select(func.count(CollectionSeedOccurrence.id))) == count
        claimed = session.get(CollectionSeedItem, "1001")
        assert claimed.status == "in_progress"
        assert claimed.detail_attempt_count == 1
        assert claimed.detail_leased_by == "detail-worker"
        assert (
            session.get(CollectionSeedItem, "1002").detail_leased_by == "other-worker"
        )


def test_occurrence_defaults_preserve_explicit_seed_metadata(queue):
    values = {
        "source_page_url": "https://example.test/explicit",
        "list_location_code": "explicit-location",
        "list_category": "explicit-category",
        "list_st_param": "explicit-param",
        "list_page": 12,
        "list_sort_key": "explicit-key",
        "list_sort_name": "explicit-name",
    }
    populate(queue, 2, values)
    claim = queue.claim_seed_detail_item("detail-worker")
    assert {key: claim[key] for key in values} == values
