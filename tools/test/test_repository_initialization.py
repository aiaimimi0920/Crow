"""Concurrent first use must share repository resources and schema setup."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest
from sqlalchemy import inspect

from src.storage import repository_core
from src.storage.repository import DatabaseSettings, PropertyRepository


@pytest.mark.parametrize("resource", ["engine", "session_factory", "initialize"])
def test_concurrent_first_use_initializes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    repo = PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{tmp_path / 'concurrent.sqlite'}", auto_create=True
        )
    )
    owner, name = {
        "engine": (repository_core, "create_engine"),
        "session_factory": (repository_core, "sessionmaker"),
        "initialize": (repository_core.Base.metadata, "create_all"),
    }[resource]
    original = getattr(owner, name)
    calls = []
    start = Barrier(8)

    def delayed_create(*args, **kwargs):
        calls.append(resource)
        # Keep first use open while the other barrier participants arrive.
        Event().wait(0.05)
        return original(*args, **kwargs)

    def first_use():
        start.wait(timeout=5)
        if resource == "initialize":
            repo.initialize()
            return repo.session_factory
        return getattr(repo, resource)

    monkeypatch.setattr(owner, name, delayed_create)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: first_use(), range(8)))
        assert calls == [resource]
        assert all(result is results[0] for result in results)
        if resource == "initialize":
            assert inspect(repo.engine).has_table("property_listing")
    finally:
        repo.engine.dispose()


def test_failed_schema_setup_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = PropertyRepository(
        DatabaseSettings(url=f"sqlite:///{tmp_path / 'retry.sqlite'}", auto_create=True)
    )
    original = repository_core.Base.metadata.create_all
    calls = 0

    def interrupted_create(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic schema interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(repository_core.Base.metadata, "create_all", interrupted_create)
    try:
        with pytest.raises(RuntimeError, match="synthetic schema interruption"):
            repo.initialize()
        repo.initialize()
        repo.initialize()
        assert calls == 2
        assert inspect(repo.engine).has_table("property_listing")
    finally:
        repo.engine.dispose()


def test_interrupted_sqlite_schema_creation_rolls_back_only_new_tables(tmp_path):
    from sqlalchemy import event

    repo = PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{tmp_path / 'atomic.sqlite'}", auto_create=True
        )
    )
    with repo.engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE preserved (value TEXT)")
        connection.exec_driver_sql("INSERT INTO preserved VALUES ('existing data')")
    created = []

    def interrupt(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("CREATE TABLE"):
            created.append(statement)
            if len(created) == 2:
                raise RuntimeError("interrupted schema creation")

    event.listen(repo.engine, "after_cursor_execute", interrupt)
    try:
        with pytest.raises(RuntimeError, match="interrupted schema creation"):
            repo.initialize()
        assert repo._initialized is False
        assert inspect(repo.engine).get_table_names() == ["preserved"]
        with repo.engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT value FROM preserved").scalar()
                == "existing data"
            )
        event.remove(repo.engine, "after_cursor_execute", interrupt)
        repo.initialize()
        assert inspect(repo.engine).has_table("manual_review_receipt")
        assert repo._initialized is True
        with repo.engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT value FROM preserved").scalar()
                == "existing data"
            )
    finally:
        if event.contains(repo.engine, "after_cursor_execute", interrupt):
            event.remove(repo.engine, "after_cursor_execute", interrupt)
        repo.engine.dispose()
