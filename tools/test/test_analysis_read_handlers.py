"""Legacy analysis HTTP health preserves live owners and degraded DB metadata."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize(
    "name",
    ["_get_analysis_prediction", "_get_analysis_health", "_get_collection_template"],
)
def test_native_analysis_read_descriptor(name):
    from src import analysis_read_handlers, server

    handler = object.__new__(server.DataHandler)
    method = getattr(handler, name)
    assert method.__self__ is handler
    assert method.__func__ is getattr(server, name)
    assert method.__module__ == analysis_read_handlers.__name__
    assert getattr(server._CONTEXT, name) is method.__func__


@pytest.mark.parametrize("now,uptime", [(5, 0), (15, 5)])
@pytest.mark.parametrize("db_failure", [False, True])
def test_health_uses_current_clock_service_and_degrades_counts(
    monkeypatch, tmp_path, now, uptime, db_failure
):
    from src import server

    saved = server._get_analysis_health
    health = Mock(return_value={"service_value": 1})
    counts = Mock(return_value={"db_total_ids": 7})
    if db_failure:
        counts.side_effect = OSError("counts unavailable")
    monkeypatch.setattr(server, "time", SimpleNamespace(time=lambda: now))
    monkeypatch.setattr(server, "_runtime_started_at", lambda: 10)
    monkeypatch.setattr(
        server,
        "AVM_SERVICE",
        SimpleNamespace(data_dir=tmp_path, health_snapshot=health),
    )
    monkeypatch.setattr(server, "DB_REPOSITORY", SimpleNamespace(enabled=True))
    monkeypatch.setattr(server, "_db_counts_snapshot", counts)
    summary = Mock(return_value={"evaluation": "current"})
    supply = Mock(return_value={"supply": 3})
    monkeypatch.setattr(server, "_avm_operator_eval_summary", summary)
    monkeypatch.setattr(server, "_db_data_supply_snapshot", supply)
    monkeypatch.setattr(server, "_db_collection_stage_snapshot", lambda: {"stage": 1})
    handler = SimpleNamespace(send_json=Mock(), send_error_json=Mock())
    saved(handler, None, "unused", {})
    health.assert_called_once_with(lightweight=True)
    summary.assert_called_once_with(tmp_path)
    supply.assert_called_once_with(24)
    result = handler.send_json.call_args.args[0]
    assert result["uptime_sec"] == uptime
    assert result["status"] == "ok"
    assert result["evaluation"] == "current"
    assert result["db_total_ids"] == (None if db_failure else 7)
    assert result.get("db_error") == ("counts unavailable" if db_failure else None)
    handler.send_error_json.assert_not_called()
