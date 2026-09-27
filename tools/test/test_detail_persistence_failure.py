"""Storage failures must not consume captured evidence or advance completion."""

import json
from functools import partial
from types import SimpleNamespace

import pytest

from src import archive_json_io, server_data_runtime
from src.collection import detail_processor
from src.collection.adapters import GenericProductAdapter
from src.collection.detail_extractors import CallableDetailExtractor
from src.collection.detail_service import DetailCollectionService


class DecisionAdapter(GenericProductAdapter):
    def accepts_detail(self, record):
        return record["accept"]


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("phase", ["records", "source", "database"])
@pytest.mark.parametrize("failure", ["fsync", "replace"])
@pytest.mark.parametrize("previous_failure", [False, True])
def test_archive_failure_preserves_detail_input_and_completion_state(
    tmp_path, monkeypatch, accepted, failure, previous_failure, phase
):
    html = tmp_path / "item-target.html"
    evidence = "<html><body>captured 中文 evidence</body></html>"
    html.write_text(evidence, encoding="utf-8")
    archive = tmp_path / "records.json"
    original = b'[{"id":"target","title":"confirmed"}]'
    archive.write_bytes(original)
    service = DetailCollectionService(tmp_path, adapter=DecisionAdapter())
    marker = service.failed_dir / "item-target.html.failed"
    if previous_failure:
        marker.write_text("prior extraction failure", encoding="utf-8")
    advanced, predictions = [], []
    source_archive = tmp_path / "source.html"
    source_archive.write_bytes(b"previous capture")
    monkeypatch.setattr(
        detail_processor,
        "get_detail_archive_path",
        lambda *_args, **_kwargs: source_archive,
    )

    def fail(*_args, **_kwargs):
        raise OSError("archive publication failed")

    def advance(*args, **_kwargs):
        advanced.append(args)

    publish = getattr(archive_json_io.os, failure)
    write_records = archive_json_io.write_records
    if phase == "source":
        monkeypatch.setattr(archive_json_io.os, failure, fail)
    elif phase == "database":
        repository = SimpleNamespace(upsert_flat_item=fail, mark_deleted=fail)
        monkeypatch.setattr(server_data_runtime, "DB_REPOSITORY", repository)
    else:

        def fail_records(*args, **kwargs):
            with monkeypatch.context() as patch:
                patch.setattr(archive_json_io.os, failure, fail)
                return write_records(*args, **kwargs)

        monkeypatch.setattr(archive_json_io, "write_records", fail_records)
    process = partial(
        service.process_html_file,
        str(html),
        get_working_item=lambda *_args, **_kwargs: {
            "file_path": str(archive),
            "data": {"id": "target", "title": "confirmed"},
        },
        get_data_path=lambda _: str(archive),
        update_item_in_json=server_data_runtime.update_item_in_json,
        remove_item_from_json=server_data_runtime.remove_item_from_json,
        persist_item_to_db=server_data_runtime.persist_item_to_db
        if phase == "database"
        else advance,
        mark_item_deleted_in_db=server_data_runtime.mark_item_deleted_in_db
        if phase == "database"
        else advance,
        evict_runtime_item=advance,
        prefer_db_task_reads=lambda: False,
        sync_avm_risk_aliases=lambda _: None,
        extract_avm_risk_features=lambda *_args, **_kwargs: None,
        log_prediction_event=lambda **event: predictions.append(event),
        queue_pending=advance,
        set_seen=advance,
        remove_pending=advance,
        detail_extractor=CallableDetailExtractor(
            lambda *_args, **_kwargs: json.dumps(
                {"accept": accepted, "title": "candidate"}
            )
        ),
    )
    process()
    process()
    assert html.read_text(encoding="utf-8") == evidence
    if phase != "database":
        assert archive.read_bytes() == original
    if phase == "source":
        assert source_archive.read_bytes() == b"previous capture"
    assert advanced == []
    assert len(predictions) == 2
    assert all(event["success"] is False for event in predictions)
    assert all(
        "archive publication failed" in event["failure_reason"] for event in predictions
    )
    assert marker.exists()
    if previous_failure:
        assert marker.read_text(encoding="utf-8") == "prior extraction failure"

    monkeypatch.setattr(archive_json_io.os, failure, publish)
    monkeypatch.setattr(archive_json_io, "write_records", write_records)
    if phase == "database":
        repository.upsert_flat_item = advance
        repository.mark_deleted = advance
    process()
    assert not html.exists()
    assert not marker.exists()
    assert source_archive.read_bytes() == evidence.encode("utf-8")
    assert len(advanced) == (3 if accepted else 2)
    committed = json.loads(archive.read_text(encoding="utf-8"))
    if accepted:
        assert len(committed) == 1
        assert committed[0]["is_processed"] is True
        assert predictions[-1]["success"] is True
    else:
        assert committed == []
