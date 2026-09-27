"""Resource failures retain distinct HTTP semantics across collection aliases."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import server
from tools.test.test_quality_http_guards import WORKER_HEADERS
from tools.test.test_quality_http_guards import api as api


@pytest.mark.parametrize(
    "path, operation",
    [
        ("/api/update_item", "apply_working_item_patch"),
        ("/api/collection/details/update_item", "apply_working_item_patch"),
        ("/api/analyze_html", "submit_html"),
        ("/api/collection/details/html", "submit_html"),
    ],
)
@pytest.mark.parametrize("item_id", [None, "", "   ", "missing"])
def test_write_resource_errors(api, monkeypatch, path, operation, item_id):
    operation_mock = Mock(return_value={"status": "id_not_found"})
    service = SimpleNamespace(**{operation: operation_mock})
    monkeypatch.setattr(server, "_detail_collection_service", lambda *_: service)
    status, _, raw = api(
        "POST", path, json.dumps({"id": item_id, "html": "evidence"}), WORKER_HEADERS
    )
    assert status == (404 if item_id == "missing" else 400), raw
    assert json.loads(raw)["error"]["code"] == (
        "AVM_DETAIL_ITEM_NOT_FOUND" if item_id == "missing" else "AVM_INVALID_ID"
    )
    assert operation_mock.call_count == (1 if item_id == "missing" else 0)


@pytest.mark.parametrize("cached", [False, True])
def test_failed_lookup_is_not_reported_as_missing(api, monkeypatch, cached):
    lookup = Mock(side_effect=RuntimeError("unavailable"))
    monkeypatch.setattr(
        server, "DB_REPOSITORY", SimpleNamespace(enabled=True, get_flat_item=lookup)
    )
    monkeypatch.setattr(
        server.RUNTIME.collection,
        "seen_ids",
        {"known": {"data": {"id": "known"}}} if cached else {},
    )
    status, _, raw = api("GET", "/api/get_item?id=known")
    assert status == (200 if cached else 503), raw
    payload = json.loads(raw)
    if cached:
        assert payload == {"id": "known"}
    else:
        assert payload["error"]["code"] == "AVM_ITEM_LOOKUP_UNAVAILABLE"


@pytest.mark.parametrize(
    "path", ["/api/collection/item?item_id=missing", "/api/collection/items/missing"]
)
@pytest.mark.parametrize(
    "mode", ["disabled", "unsupported", "noncallable", "missing", "found"]
)
def test_observer_distinguishes_unavailable_and_missing(api, monkeypatch, path, mode):
    payload = {
        "found": mode == "found",
        "item_id": "missing",
        "item": {"id": "missing"},
    }
    repository = SimpleNamespace(enabled=mode != "disabled")
    lookup = Mock(return_value=payload)
    if mode == "noncallable":
        repository.collection_observer_item_detail = "not-callable"
    elif mode != "unsupported":
        repository.collection_observer_item_detail = lookup
    monkeypatch.setattr(server, "DB_REPOSITORY", repository)
    status, _, raw = api("GET", path)
    expected = {
        "disabled": 503,
        "unsupported": 503,
        "noncallable": 503,
        "missing": 404,
        "found": 200,
    }
    assert status == expected[mode], raw
    if mode in ("disabled", "unsupported", "noncallable"):
        lookup.assert_not_called()
        assert json.loads(raw)["error"]["code"] == "COLLECTION_OBSERVER_UNAVAILABLE"
    elif mode == "found":
        assert json.loads(raw)["found"] is True
    else:
        assert json.loads(raw)["error"]["code"] == "AVM_DETAIL_ITEM_NOT_FOUND"


def test_missing_observer_id_is_invalid_even_without_storage(api, monkeypatch):
    monkeypatch.setattr(server, "DB_REPOSITORY", SimpleNamespace(enabled=False))
    status, _, raw = api("GET", "/api/collection/item")
    assert status == 400, raw
    assert json.loads(raw)["error"]["code"] == "AVM_INVALID_ID"


def test_unexpected_update_result_is_not_reported_as_missing(api, monkeypatch):
    service = SimpleNamespace(
        apply_working_item_patch=Mock(return_value={"status": "bad"})
    )
    monkeypatch.setattr(server, "_detail_collection_service", lambda *_: service)
    status, _, raw = api("POST", "/api/update_item", '{"id":"known"}', WORKER_HEADERS)
    assert status == 500, raw
    assert json.loads(raw)["error"]["code"] == "AVM_DETAIL_UPDATE_ITEM_FAILED"
