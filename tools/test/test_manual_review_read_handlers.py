"""Native manual-review read wiring and history pagination behavior."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.manual_review_read_handlers import ReviewReadHandlers


@pytest.mark.parametrize("name", ReviewReadHandlers.__all__)
def test_native_review_read_descriptor(name):
    from src import manual_review_read_handlers, server

    handler = object.__new__(server.DataHandler)
    method = getattr(handler, name)
    assert method.__self__ is handler
    assert method.__func__ is getattr(server, name)
    assert method.__module__ == manual_review_read_handlers.__name__
    assert getattr(server._CONTEXT, name) is method.__func__


@pytest.mark.parametrize(
    "kind,key,count",
    [
        ("backup_repairs", "repairs", "repair_count"),
        ("integrity_history", "history", "transition_count"),
    ],
)
@pytest.mark.parametrize(
    "limit,expected", [("0", []), ("2", [3, 2]), ("bad", [3, 2, 1])]
)
def test_history_uses_current_owner_and_orders_after_limit(
    monkeypatch, tmp_path, kind, key, count, limit, expected
):
    from src import server

    saved = getattr(server, "_get_manual_review_" + kind)
    monkeypatch.setattr(server, "AVM_SERVICE", SimpleNamespace(data_dir=tmp_path))
    records = [{"id": n} for n in (1, 2, 3)]
    load = Mock(return_value=records)
    runtime = Mock(return_value={"runtime": "current"})
    monkeypatch.setattr(server, "load_manual_review_control_plane_" + kind, load)
    monkeypatch.setattr(server, "_manual_review_control_plane_runtime_summary", runtime)
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    saved(handler, None, "unused", {"limit": [limit]})
    load.assert_called_once_with(tmp_path)
    runtime.assert_called_once_with(tmp_path)
    payload = handler.send_json.call_args.args[0]
    assert [row["id"] for row in payload[key]] == expected
    assert payload[count] == len(expected)
    assert payload["runtime"] == "current"
    assert records == [{"id": n} for n in (1, 2, 3)]
    handler.send_error_json.assert_not_called()
