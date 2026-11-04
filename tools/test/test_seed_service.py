from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.archive_json_io import read_records
from src.collection.adapters import TaobaoJudicialAuctionAdapter
from src.collection.seed_service import SeedCollectionService
from src.collection_archive_records import CollectionArchiveRecords
from src.runtime_state import RuntimeState


def test_submit_batch_writes_new_seed_file_for_new_items(tmp_path: Path):
    data_root = tmp_path / "datas"
    data_root.mkdir()
    target_file = data_root / "2026-05-18.json"
    runtime = RuntimeState()
    archives = CollectionArchiveRecords(
        runtime=lambda: runtime,
        exists=lambda path: Path(path).exists(),
        load=read_records,
    )

    seen_ids: dict[str, dict[str, object]] = {}
    pending_tasks: list[str] = []
    persisted: list[tuple[dict[str, object], str, dict[str, object] | None]] = []

    service = SeedCollectionService(
        repository=None,
        jobs_dir=None,
        data_root=str(data_root),
        adapter=TaobaoJudicialAuctionAdapter(),
    )
    result = service.submit_batch(
        {
            "items": [
                {
                    "id": "123456",
                    "title": "测试法拍房",
                    "currentPrice": 1234567,
                    "initialPrice": 1000000,
                    "auction_date": "2026-05-18 10:00:00",
                    "auction_start_time": "2026-05-17 10:00:00",
                    "url": "https://sf-item.taobao.com/sf_item/123456.htm",
                    "status": "done",
                    "bidCount": 2,
                    "bidderCount": 1,
                    "applyCount": 1,
                    "watchCount": 10,
                    "remindCount": 5,
                    "viewCount": 30,
                    "location": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
                    "full_address": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
                    "district": "西湖区",
                    "city": "杭州市",
                    "latitude": 30.27,
                    "longitude": 120.15,
                    "coordinate_source": "list",
                    "auction_round": "一拍",
                    "housing_type": "住宅",
                    "deposit": 100000,
                    "is_processed": False,
                }
            ],
            "raw_payload": [{"id": "123456"}],
            "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
        },
        parse_price=lambda value: value,
        safe_int=lambda value: value,
        prefer_db_task_reads=lambda: False,
        get_seen_entry=lambda item_id: seen_ids.get(item_id),
        get_flat_item=lambda item_id: None,
        get_data_path=lambda date_str: str(target_file),
        update_file_global=archives.update_file_global,
        persist_item_to_db=lambda item, event_type, event_payload=None: (
            persisted.append((item, event_type, event_payload))
        ),
        evict_runtime_item=lambda item_id: None,
        archive_list_payload=lambda *_args, **_kwargs: None,
        set_seen=lambda item_id, entry: seen_ids.__setitem__(item_id, entry),
        queue_pending=lambda item_id: pending_tasks.append(item_id) or True,
    )

    assert result == {"status": "ok", "new": 1}
    assert target_file.exists()
    payload = json.loads(target_file.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["id"] == "123456"


def test_next_task_propagates_database_failures_instead_of_reporting_completion() -> (
    None
):
    class FailingRepository:
        enabled = True

        def count_search_tasks(self):
            return 1

        def claim_search_task(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

    service = SeedCollectionService(
        repository=FailingRepository(), adapter=TaobaoJudicialAuctionAdapter()
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.next_task("worker-1")


def test_submit_batch_propagates_existing_item_lookup_failures(tmp_path: Path) -> None:
    class Adapter:
        search_task_policy = object()

        def item_id(self, item):
            return str(item["id"])

        def build_seed_record(self, item, *, parse_number, safe_int):
            return dict(item)

        def accepts_seed(self, item, prepared_item):
            return True

        def sync_record(self, record):
            return None

        def partition_key(self, record):
            return "2026-05-18"

    persisted = []
    service = SeedCollectionService(adapter=Adapter())

    with pytest.raises(OSError, match="database unavailable"):
        service.submit_batch(
            {"items": [{"id": "item-1", "title": "fixture"}]},
            parse_price=lambda value: value,
            safe_int=lambda value: value,
            prefer_db_task_reads=lambda: True,
            get_seen_entry=lambda item_id: None,
            get_flat_item=lambda item_id: (_ for _ in ()).throw(
                OSError("database unavailable")
            ),
            get_data_path=lambda date_str: str(tmp_path / "items.json"),
            update_file_global=lambda *args, **kwargs: None,
            persist_item_to_db=lambda *args, **kwargs: persisted.append(args),
            evict_runtime_item=lambda item_id: None,
            archive_list_payload=lambda *args, **kwargs: None,
            set_seen=lambda *_args: None,
            queue_pending=lambda _item_id: True,
        )

    assert persisted == []
