import pytest

from src.archive_json_io import read_records
from src.collection import search_bootstrap
from src.collection.search_bootstrap import iter_job_snapshots, load_all_location_codes
from src.collection_jobs import CollectionJobManager
from src.avm.service_data import AVMDataMixin
from src import server
from src.runtime_json import loads_bounded_json


def _deep_json(levels=300):
    return '{"x":' * levels + '0' + '}' * levels


def test_bounded_json_reader_rejects_deep_nesting_without_decoder_recursion():
    with pytest.raises(ValueError, match="nesting"):
        loads_bounded_json(_deep_json(2000))


def test_collection_job_receipts_fail_closed_and_list_skips_invalid_json(tmp_path):
    manager = CollectionJobManager(tmp_path)
    manager.root.mkdir(parents=True)
    (manager.root / ("a" * 32 + ".json")).write_text(_deep_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="nesting"):
        manager.get("a" * 32)
    assert manager.list() == []


def test_search_job_snapshots_skip_deep_json_and_keep_shallow_contract(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "deep.json").write_text(_deep_json(), encoding="utf-8")
    assert iter_job_snapshots(jobs) == []

    (jobs / "valid.json").write_text(
        '{"110000":{"50025969":{"now_session_id":"s1","st_param":{"2":{"pages":[1],"max_page":1}}}}}',
        encoding="utf-8",
    )
    assert iter_job_snapshots(jobs) == [
        {
            "location_code": "110000",
            "category": "50025969",
            "sort_param": "2",
            "pages": [1],
            "max_page": 1,
            "is_done": False,
            "need_try": True,
            "dispatched_page": 0,
            "now_session_id": "s1",
            "last_update_time": "",
            "category_all_done": False,
        }
    ]


def test_archive_reader_rejects_deep_json_and_reads_records(tmp_path):
    deep = tmp_path / "deep.json"
    deep.write_text(_deep_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="nesting"):
        read_records(deep)

    valid = tmp_path / "valid.json"
    valid.write_text('[{"id":"one"}]', encoding="utf-8")
    assert read_records(valid) == [{"id": "one"}]



def test_collection_data_loader_skips_deep_json_and_keeps_valid_records(tmp_path, monkeypatch):
    (tmp_path / "deep.json").write_text(_deep_json(), encoding="utf-8")
    (tmp_path / "valid.json").write_text('{"id":"valid-item","status":"pending"}', encoding="utf-8")
    seen = []
    monkeypatch.setattr(server.RUNTIME.collection, "seen_ids", {})
    monkeypatch.setattr(server.RUNTIME.collection, "pending_tasks", [])
    monkeypatch.setattr(server, "DB_REPOSITORY", type("Repo", (), {"enabled": False})())
    monkeypatch.setattr(server, "sync_collection_record", lambda item: seen.append(item["id"]))

    server.load_data(tmp_path)

    assert seen == ["valid-item"]


def test_avm_raw_record_stream_skips_deep_json(tmp_path):
    class Reader(AVMDataMixin):
        repository = None

        def __init__(self, paths):
            self.paths = paths

        def _iter_data_files(self):
            return self.paths

    deep = tmp_path / "deep-runtime.json"
    valid = tmp_path / "valid-runtime.json"
    deep.write_text(_deep_json(), encoding="utf-8")
    valid.write_text('[{"id":"valid-item"}]', encoding="utf-8")
    assert list(Reader([str(deep), str(valid)])._iter_raw_record_stream()) == [
        {"id": "valid-item"}
    ]



def test_location_code_loader_handles_deep_children_iteratively(tmp_path, monkeypatch):
    levels = 1200
    root = {}
    node = root
    for _ in range(levels - 1):
        child = {}
        node["code"] = "000001"
        node["children"] = [child]
        node = child
    node["code"] = "000001"
    node["children"] = []
    (tmp_path / "all_locations.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(search_bootstrap, "load_json_file", lambda _path: [root])

    codes = load_all_location_codes(tmp_path)

    assert len(codes) == levels
    assert set(codes) == {"000001"}


def test_search_snapshot_loader_does_not_hide_unexpected_loader_errors(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "unexpected.json").write_text("{}", encoding="utf-8")

    def fail(_path):
        raise RuntimeError("unexpected loader failure")

    monkeypatch.setattr(search_bootstrap, "load_json_file", fail)
    with pytest.raises(RuntimeError, match="unexpected loader failure"):
        iter_job_snapshots(jobs)