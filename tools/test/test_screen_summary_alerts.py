"""Screen summary and legacy alert persistence contracts on both hosts."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


@pytest.fixture(params=[False, True])
def host(request):
    from src import server, server_collection_operations

    return server if request.param else server_collection_operations


def test_native_owners_and_operations_exit_cloning(host):
    from src import server
    from src.screen_alert_store import ScreenAlertStore
    from src.screen_result_summary import ScreenResultSummary

    for owner in (ScreenResultSummary, ScreenAlertStore):
        for name in owner.__all__:
            assert isinstance(getattr(host, name).__self__, owner)
            if host is server:
                assert getattr(host._CONTEXT, name) is getattr(host, name)
    assert "server_collection_operations" in server._NATIVE_MODULES
    assert not hasattr(server, "_IMPLEMENTATION_MODULES")


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, "unknown"),
        ("bad", "unknown"),
        ([], "unknown"),
        (0.4499, "low"),
        ("0.45", "medium"),
        (0.7499, "medium"),
        (0.75, "high"),
        (float("nan"), "low"),
        (float("inf"), "high"),
    ],
)
def test_confidence_boundaries(host, value, expected):
    assert host._prediction_confidence_bucket(value) == expected


def test_summary_counts_each_blocker_but_each_blocked_result_once(host):
    results = [
        {
            "id": "first",
            "prediction": {
                "strategy": "z",
                "confidence": 0.8,
                "trace": {"subject_coordinate_strategy": "map"},
                "manual_review_recommended": True,
            },
            "alert_blockers": [
                "manual_review_required",
                "manual_review_required",
                "risk_validation_invalid",
                "risk_validation_incomplete",
            ],
            "margin": 0.12345,
            "is_malignant_risk": True,
        },
        {
            "id": "second",
            "prediction": {"strategy": "a", "confidence": 0.5},
            "margin": True,
            "meets_alert_threshold": True,
        },
        {"id": "third", "margin": "0.9"},
    ]
    result = host.summarize_screen_results(results)
    assert result == {
        "strategy_counts": {"a": 1, "unknown": 1, "z": 1},
        "coordinate_strategy_counts": {"map": 1, "unknown": 2},
        "confidence_bucket_counts": {"high": 1, "medium": 1, "unknown": 1},
        "malignant_risk_count": 1,
        "alert_candidate_count": 1,
        "manual_review_count": 1,
        "blocked_reason_counts": {
            "manual_review_required": 2,
            "risk_validation_incomplete": 1,
            "risk_validation_invalid": 1,
        },
        "manual_review_blocked_count": 1,
        "risk_validation_blocked_count": 1,
        "average_margin": 0.5617,
        "top_result_id": "first",
    }
    assert list(result["strategy_counts"]) == ["a", "unknown", "z"]
    empty = host.summarize_screen_results([])
    assert empty["average_margin"] is None and empty["top_result_id"] is None
    assert empty["blocked_reason_counts"] == {}


def test_saved_summary_reads_current_bucket_and_rejects_invalid_shapes(
    host, monkeypatch
):
    summary = host.summarize_screen_results
    monkeypatch.setattr(host, "_prediction_confidence_bucket", lambda value: "replaced")
    assert summary([{"id": "x"}])["confidence_bucket_counts"] == {"replaced": 1}
    with pytest.raises(AttributeError):
        summary([{"id": "x", "prediction": "invalid"}])
    with pytest.raises(KeyError):
        summary([{}])


@pytest.fixture
def alert_path(host, tmp_path, monkeypatch):
    root = tmp_path / "alerts"
    path = root / "alerts.json"
    monkeypatch.setattr(host, "AVM_DIR", str(root))
    monkeypatch.setattr(host, "AVM_ALERTS_PATH", str(path))
    return path


def test_alert_empty_noop_and_id_replacement_under_current_lock(
    host, alert_path, monkeypatch
):
    writer = host.write_avm_alerts
    writer([])
    assert not alert_path.parent.exists()
    events = []

    @contextmanager
    def lock():
        events.append("enter")
        yield
        assert json.loads(alert_path.read_text(encoding="utf-8")) == [
            {"id": "1", "text": "更新"},
            {"id": 2},
            {"id": 3, "last": True},
        ]
        events.append("exit")

    monkeypatch.setattr(host, "RUNTIME", SimpleNamespace(file_lock=lock()))
    alert_path.parent.mkdir()
    alert_path.write_text('[{"id":1,"old":true},{"id":2}]', encoding="utf-8")
    writer([{"id": "1", "text": "更新"}, {"id": 3}, {"id": 3, "last": True}])
    assert events == ["enter", "exit"]
    assert "更新" in alert_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("previous", ["bad json", "{}", "null"])
def test_invalid_existing_alert_document_uses_legacy_empty_fallback(
    host, alert_path, previous
):
    alert_path.parent.mkdir()
    alert_path.write_text(previous, encoding="utf-8")
    host.write_avm_alerts([{"id": "new"}])
    assert json.loads(alert_path.read_text(encoding="utf-8")) == [{"id": "new"}]


def test_invalid_alert_entries_and_write_errors_propagate(host, alert_path):
    alert_path.parent.mkdir()
    alert_path.write_text("[null]", encoding="utf-8")
    with pytest.raises(AttributeError):
        host.write_avm_alerts([{"id": "new"}])
    assert alert_path.read_text(encoding="utf-8") == "[null]"
    alert_path.write_text("[]", encoding="utf-8")
    with pytest.raises(KeyError):
        host.write_avm_alerts([{}])
    alert_path.unlink()
    alert_path.mkdir()
    with pytest.raises(OSError):
        host.write_avm_alerts([{"id": "new"}])
