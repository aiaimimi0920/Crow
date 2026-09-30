"""English code names must not change existing database or import identities."""

from __future__ import annotations

import hashlib
import json
import pickle

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from src.storage import models

ALIASES = {
    "FapaiSeedScanJob": "CollectionSeedScanJob",
    "FapaiSeedScanProgress": "CollectionSeedScanProgress",
    "FapaiSeedItem": "CollectionSeedItem",
    "FapaiAnalysisRun": "CollectionAnalysisRun",
    "FapaiSeedOccurrence": "CollectionSeedOccurrence",
}


@pytest.mark.parametrize("legacy,canonical", ALIASES.items())
def test_canonical_and_legacy_imports_are_the_same_mapped_class(legacy, canonical):
    previous = getattr(models, legacy)
    current = getattr(models, canonical)
    assert previous is current
    assert current.__name__ == canonical
    assert previous.__table__ is current.__table__
    # Trusted in-repository protocol-0 class references model older imports.
    reference = f"csrc.storage.models\n{legacy}\n.".encode("ascii")
    assert pickle.loads(reference) is current
    assert pickle.loads(pickle.dumps(current)) is current
    instance = current()
    primary_key = next(iter(current.__table__.primary_key)).name
    setattr(instance, primary_key, "legacy-fixture")
    serialized = pickle.dumps(instance, protocol=0)
    legacy_serialized = serialized.replace(
        f"csrc.storage.models\n{canonical}\n".encode("ascii"), reference[:-1]
    )
    restored = pickle.loads(legacy_serialized)
    assert type(restored) is current
    assert getattr(restored, primary_key) == "legacy-fixture"


def test_postgres_and_sqlite_ddl_match_pre_rename_baseline():
    signature = {}
    for name, dialect in (
        ("postgresql", postgresql.dialect()),
        ("sqlite", sqlite.dialect()),
    ):
        signature[name] = [
            str(CreateTable(table).compile(dialect=dialect))
            for table in models.Base.metadata.sorted_tables
        ] + sorted(
            str(CreateIndex(index).compile(dialect=dialect))
            for table in models.Base.metadata.sorted_tables
            for index in table.indexes
        )
    serialized = json.dumps(signature, sort_keys=True, ensure_ascii=True)
    # Captured before class renaming on c2b9e944: includes every table, FK,
    # column, constraint, index and dialect-specific SQL representation.
    assert hashlib.sha256(serialized.encode()).hexdigest() == (
        "e75691b5fafee1f7c09ef9fab18f8fa0b50700cb8b81b34453f0833f14cc26e8"
    )


def test_new_and_old_imports_read_one_existing_legacy_table(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'existing.sqlite3').as_posix()}")
    models.Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO fapai_seed_item (item_id, status, detail_attempt_count) "
                "VALUES ('existing-record', 'pending_detail', 0)"
            )
        )
    with Session(engine) as session:
        canonical = session.get(models.CollectionSeedItem, "existing-record")
        legacy = session.get(models.FapaiSeedItem, "existing-record")
        assert canonical is legacy
        assert canonical.item_id == "existing-record"
        assert canonical.status == "pending_detail"
    engine.dispose()
