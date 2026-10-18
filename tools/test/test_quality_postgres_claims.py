"""Concurrency proof in a dedicated disposable database, never production."""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, get_ident
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url

from src.storage.models import FapaiSeedItem, FapaiSeedScanProgress, PropertySearchTask
from src.storage.repository import DatabaseSettings, PropertyRepository


pytestmark = [pytest.mark.security, pytest.mark.integration]


@pytest.fixture
def repository():
    value = os.getenv("CROW_TEST_POSTGRES_URL")
    if not value:
        pytest.skip("CROW_TEST_POSTGRES_URL must name a dedicated crow_quality database")
    url = make_url(value)
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "crow_quality":
        pytest.fail("Concurrency tests require a loopback crow_quality database")
    schema = "claim_test_" + uuid4().hex
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine.dispose()
    isolated = url.update_query_dict({"options": f"-csearch_path={schema}"})
    repo = PropertyRepository(DatabaseSettings(
        url=isolated.render_as_string(hide_password=False), echo=False,
        enable_postgis=False, auto_create=True, enabled=True,
    ))
    repo.initialize()
    yield repo
    repo.engine.dispose()


@pytest.mark.parametrize("kind", ["search", "page", "page_parallel", "page_closure", "detail", "analysis"])
def test_two_workers_never_claim_the_same_active_work(repository, kind):
    if kind == "search":
        assert repository.bootstrap_search_task({"location_code": "440115", "category": "50025969", "st_param": "2"})
        table = "property_search_task"
        claim = repository.claim_search_task
    elif kind.startswith("page"):
        repository.ensure_seed_scan_job(
            {"job_key": "concurrent", "location_code": "440115", "category": "50025969"},
            sort_specs=[{"sort_key": "default", "sort_name": "Default", "st_param": "0"}],
        )
        table = "fapai_seed_scan_job"
        claim = lambda worker: repository.claim_seed_scan_page(
            worker, parallel_sorts=kind in {"page_parallel", "page_closure"},
            breadth_first=kind == "page_closure",
        )
    else:
        with repository.session_factory.begin() as session:
            payload = {"id": "1001"}
            if kind == "analysis":
                payload["_raw_detail_artifacts"] = {"detail_html_path": "retained-evidence.html"}
            session.add(FapaiSeedItem(item_id="1001", source_item_id="1001",
                                      status="raw_detail_captured" if kind == "analysis" else "pending_detail",
                                      source_payload=payload))
        table = "fapai_seed_item"
        claim = repository.claim_seed_raw_detail_item if kind == "analysis" else repository.claim_seed_detail_item
    barrier = Barrier(2)
    synchronized = set()

    def overlap(_connection, _cursor, statement, _parameters, _context, _many):
        identity = get_ident()
        if identity not in synchronized and f"FROM {table}" in statement and "FOR UPDATE" not in statement:
            synchronized.add(identity)
            barrier.wait(timeout=10)

    event.listen(repository.engine, "after_cursor_execute", overlap)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["worker-a", "worker-b"]))
    finally:
        event.remove(repository.engine, "after_cursor_execute", overlap)
    assert len(synchronized) == 2
    assert sum(result is not None for result in results) == 1
    with repository.session_factory() as session:
        model = PropertySearchTask if kind == "search" else FapaiSeedScanProgress if kind.startswith("page") else FapaiSeedItem
        row = session.scalars(select(model)).one()
        assert (row.detail_leased_by if kind in {"detail", "analysis"} else row.leased_by) in {"worker-a", "worker-b"}
