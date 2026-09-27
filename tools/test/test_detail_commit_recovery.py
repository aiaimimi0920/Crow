"""Real collection storage proves recovery and retained evidence at commit boundaries."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import archive_json_io
from src.collection import detail_processor
from src.collection.adapters import GenericProductAdapter
from src.collection.detail_failures import DetailFailures

SENSITIVE = "synthetic-private-ai-content"
EVIDENCE = "<html><body>Inventory 12. <div id='J_NoticeDetail'>Source notice</div></body></html>"


@pytest.fixture
def captured(tmp_path, monkeypatch):
    from src.collection_application import create_application
    from src.storage import CollectionRepository, DatabaseSettings

    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv(
        "FAPAI_NAS_AUTH_RECOVERY_STATE_PATH", str(tmp_path / "auth.json")
    )
    adapter = GenericProductAdapter(source_platform="catalog_x")
    settings = DatabaseSettings(
        url=f"sqlite:///{(tmp_path / 'collection.sqlite').as_posix()}",
        enabled=True,
        auto_create=True,
    )
    repository = CollectionRepository(settings, adapter=adapter)
    repository.initialize()
    app = create_application(data_root=tmp_path, repository=repository, adapter=adapter)
    app.host._prefer_db_task_reads = lambda: True
    item_id = adapter.item_id({"id": "sku-9"})
    seed = {
        "id": "sku-9",
        "title": "Confirmed seed",
        "url": "https://catalog.example/items/sku-9",
        "legacy_extra": {"preserve": True},
    }
    assert app.host.handle_seed_batch_submission({"items": [seed]})["new"] == 1
    html = tmp_path / "html" / f"item-{item_id}.html"
    html.parent.mkdir(exist_ok=True)
    html.write_text(EVIDENCE, encoding="utf-8")
    events, calls = [], []

    def extract(content, **_options):
        calls.append(content)
        return json.dumps(
            {
                "name": "Candidate",
                "inventory": 12,
                "extra_note": SENSITIVE,
                "detail_text_path": "untrusted-reference",
            }
        )

    def forbidden(*_args, **_kwargs):
        pytest.fail("generic collection invoked auction extraction")

    app.host.llm_helper = SimpleNamespace(
        extract_product_data=extract,
        extract_auction_data=forbidden,
        extract_avm_risk_features=forbidden,
        log_prediction_event=lambda **event: events.append(event),
    )
    try:
        yield SimpleNamespace(
            app=app,
            repository=repository,
            settings=settings,
            adapter=adapter,
            root=tmp_path,
            html=html,
            item_id=item_id,
            events=events,
            calls=calls,
        )
    finally:
        app.close()
        repository.engine.dispose()


def assert_committed(case, evidence=EVIDENCE):
    from src.storage import CollectionRepository

    reopened = CollectionRepository(case.settings, adapter=case.adapter)
    try:
        record = reopened.get_flat_item(case.item_id)
        assert record["is_processed"] is True
        assert record["source_item_id"] == "sku-9"
        assert record["source_platform"] == "catalog_x"
        assert record["legacy_extra"] == {"preserve": True}
        assert record["inventory"] == 12
        assert record["detail_text_path"] != "untrusted-reference"
        assert (case.root / record["detail_archive_path"]).read_text(
            encoding="utf-8"
        ) == evidence
        assert (case.root / record["detail_text_path"]).is_file()
        assert reopened.counts_snapshot()["db_total_ids"] == 1
        assert not case.html.exists()
        return record
    finally:
        reopened.engine.dispose()


@pytest.mark.parametrize(
    "stage",
    [
        "lookup",
        "extraction",
        "model_result",
        "archive",
        "artifacts",
        "json",
        "database",
    ],
)
def test_failed_detail_preserves_capture_and_seed_then_retries(
    captured, monkeypatch, caplog, stage
):
    case = captured
    original = case.repository.get_flat_item(case.item_id)
    caplog.set_level(logging.INFO)

    def fail(*_args, **_kwargs):
        raise OSError(SENSITIVE)

    with monkeypatch.context() as patch:
        targets = {
            "lookup": (case.repository, "get_flat_item"),
            "extraction": (case.app.host.llm_helper, "extract_product_data"),
            "archive": (detail_processor, "write_archive_text"),
            "artifacts": (detail_processor, "extract_detail_artifacts"),
            "json": (case.app.host, "update_item_in_json"),
            "database": (case.repository, "upsert_flat_item"),
        }
        if stage == "model_result":
            patch.setattr(
                case.app.host.llm_helper,
                "extract_product_data",
                lambda *_args, **_kwargs: SENSITIVE,
            )
        else:
            patch.setattr(*targets[stage], fail)
        case.app.host.process_single_file(str(case.html))
        case.app.host.process_single_file(str(case.html))

    assert case.html.read_text(encoding="utf-8") == EVIDENCE
    assert case.repository.get_flat_item(case.item_id) == original
    assert not any(event["success"] for event in case.events)
    receipt_path = DetailFailures(case.root).path(case.item_id)
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    assert receipt["stage"] == stage and receipt["attempts"] == 2
    assert SENSITIVE not in caplog.text + receipt_text + json.dumps(case.events)
    submissions = []
    with monkeypatch.context() as patch:
        patch.setattr(
            case.app.host.executor, "submit", lambda *_args: submissions.append(True)
        )
        case.app.host.submit_task(str(case.html))
    assert not submissions
    assert not case.app.host.RUNTIME.processing.snapshot()

    case.app.host.process_single_file(str(case.html))
    assert_committed(case)
    assert not receipt_path.exists()
    assert case.events[-1]["success"] is True


def test_telemetry_failure_does_not_undo_completed_collection(captured, caplog):
    def fail(**_event):
        raise RuntimeError(SENSITIVE)

    captured.app.host.llm_helper.log_prediction_event = fail
    captured.app.host.process_single_file(str(captured.html))
    assert_committed(captured)
    assert SENSITIVE not in caplog.text


@pytest.mark.parametrize("stage", ["artifacts", "database"])
def test_failed_refresh_preserves_evidence_of_committed_record(
    captured, monkeypatch, stage
):
    case = captured
    case.app.host.process_single_file(str(case.html))
    original = assert_committed(case)
    evidence = {
        case.root / original[key]: (case.root / original[key]).read_bytes()
        for key in ("detail_archive_path", "detail_text_path", "notice_text_path")
    }
    replacement = EVIDENCE.replace("Source notice", "Updated source notice")
    case.html.write_text(replacement, encoding="utf-8")
    case.events.clear()

    def fail(*_args, **_kwargs):
        raise OSError("isolated refresh failure")

    with monkeypatch.context() as patch:
        target = (
            (detail_processor, "extract_detail_artifacts")
            if stage == "artifacts"
            else (case.repository, "upsert_flat_item")
        )
        patch.setattr(*target, fail)
        case.app.host.process_single_file(str(case.html))

    assert case.repository.get_flat_item(case.item_id) == original
    assert all(path.read_bytes() == content for path, content in evidence.items())
    assert case.html.read_text(encoding="utf-8") == replacement
    assert not any(event["success"] for event in case.events)
    case.app.host.process_single_file(str(case.html))
    assert_committed(case, replacement)
    assert all(path.read_bytes() == content for path, content in evidence.items())


def test_model_cannot_rewrite_seed_identity(captured):
    case = captured
    extracted = json.loads(case.app.host.llm_helper.extract_product_data(EVIDENCE))
    extracted.update(
        source_platform="unrelated",
        source_item_id="foreign-id",
        source_url="https://unrelated.invalid",
        url="https://unrelated.invalid",
    )
    case.app.host.llm_helper.extract_product_data = lambda *_args, **_kwargs: (
        json.dumps(extracted)
    )
    case.app.host.process_single_file(str(case.html))
    record = assert_committed(case)
    assert record["source_url"] == "https://catalog.example/items/sku-9"


def test_capture_arriving_during_processing_survives_cleanup(captured):
    case = captured
    extract = case.app.host.llm_helper.extract_product_data
    replacement = EVIDENCE + "<!-- newer capture -->"

    def replace_capture(content, **options):
        with case.app.host.RUNTIME.collection.lock:
            archive_json_io.write_text(case.html, replacement)
        case.app.host.llm_helper.extract_product_data = extract
        return extract(content, **options)

    case.app.host.llm_helper.extract_product_data = replace_capture
    case.app.host.process_single_file(str(case.html))
    assert case.html.read_text(encoding="utf-8") == replacement
    first = case.repository.get_flat_item(case.item_id)
    assert (case.root / first["detail_archive_path"]).read_text(
        encoding="utf-8"
    ) == EVIDENCE
    case.app.host.process_single_file(str(case.html))
    assert_committed(case, replacement)


def test_sidecar_replace_failure_retains_previous_evidence(captured, monkeypatch):
    case = captured
    original_replace = archive_json_io.os.replace
    notice = case.root / "confirmed.notice.txt"
    notice.write_text("confirmed notice", encoding="utf-8")
    from src import detail_artifacts

    original_path = detail_artifacts.get_detail_archive_path

    def archive_path(root, date, item_id, **options):
        return (
            notice
            if str(item_id).endswith(".notice")
            else original_path(root, date, item_id, **options)
        )

    def fail_notice(source, destination):
        if Path(destination) == notice:
            raise OSError("isolated sidecar replace failure")
        return original_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(detail_artifacts, "get_detail_archive_path", archive_path)
        patch.setattr(archive_json_io.os, "replace", fail_notice)
        case.app.host.process_single_file(str(case.html))
    assert notice.read_text(encoding="utf-8") == "confirmed notice"
    assert not case.repository.get_flat_item(case.item_id)["is_processed"]
    assert case.html.read_text(encoding="utf-8") == EVIDENCE
    case.app.host.process_single_file(str(case.html))
    assert_committed(case)


def test_legacy_text_capture_keeps_raw_evidence_separate(captured):
    case = captured
    text_path = case.root / f"item-{case.item_id}.txt"
    case.html.replace(text_path)
    case.html = text_path
    case.app.host.process_single_file(str(text_path))
    record = assert_committed(case)
    assert record["detail_archive_path"] != record["detail_text_path"]


def test_source_field_retry_retains_capture_until_second_extraction(captured):
    from src.collection.detail_service import DetailCollectionService

    class RetryAdapter(GenericProductAdapter):
        def retry_reason(self, record):
            return None if record.get("inventory") else "inventory is missing"

    case = captured
    extract = case.app.host.llm_helper.extract_product_data
    case.app.host._detail_collection_service = lambda: DetailCollectionService(
        case.root,
        repository=case.repository,
        adapter=RetryAdapter(source_platform="catalog_x"),
        dispatch_lock=case.app.host.RUNTIME.collection.lock,
    )
    case.app.host.llm_helper.extract_product_data = lambda *_args, **_kwargs: "{}"
    case.app.host.process_single_file(str(case.html))
    assert case.html.read_text(encoding="utf-8") == EVIDENCE
    assert not case.repository.get_flat_item(case.item_id)["is_processed"]
    retry = case.root / "retry" / f"item-{case.item_id}.html.retry"
    assert retry.is_file()
    case.app.host.llm_helper.extract_product_data = extract
    case.app.host.process_single_file(str(case.html))
    assert_committed(case)
    assert not retry.exists()
