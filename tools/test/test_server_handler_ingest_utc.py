from __future__ import annotations

import datetime
import threading
from unittest import mock

import src.server as server_module


class _FakeHandler:
    path = "/api/avm/screen"

    def __init__(self):
        self.response = None
        self.error = None

    def send_json(self, payload):
        self.response = payload

    def send_error_json(self, **kwargs):
        self.error = kwargs


def test_screen_alert_created_at_uses_utc_clock_and_legacy_format():
    handler = _FakeHandler()
    utc_now = datetime.datetime(2026, 9, 22, 3, 4, 5, tzinfo=datetime.timezone.utc)
    prediction = {
        "predicted_price": 100.0,
        "predicted_unit_price": 10.0,
        "risk_validation": {},
        "manual_review_recommended": False,
        "manual_review_reasons": [],
    }
    service = mock.Mock()
    service.predict_by_item_data.return_value = prediction
    service.model_version.return_value = "test-model"
    written_alerts = []

    with (
        mock.patch.object(server_module, "_require_control_plane", return_value=True),
        mock.patch.object(
            server_module,
            "_read_json_body",
            return_value=(True, {"items": [{"id": "item-1"}], "margin_threshold": 0.0}),
        ),
        mock.patch.object(server_module.RUNTIME.collection, "lock", threading.Lock()),
        mock.patch.object(
            server_module.RUNTIME.collection, "seen_ids", {"item-1": {"data": {"starting_price": 50.0}}}
        ),
        mock.patch.object(server_module, "AVM_SERVICE", service),
        mock.patch.object(
            server_module,
            "build_avm_result",
            return_value={"id": "item-1", "margin": 0.5, "is_malignant_risk": False},
        ),
        mock.patch.object(server_module, "build_alert_blockers", return_value=[]),
        mock.patch.object(server_module, "summarize_screen_results", return_value={}),
        mock.patch.object(
            server_module, "write_avm_alerts", side_effect=written_alerts.extend
        ),
        mock.patch.object(server_module, "_utc_now", return_value=utc_now) as clock,
    ):
        server_module._post_analysis_screen(handler)

    assert handler.error is None
    assert handler.response["alerts_written"] == 1
    assert len(written_alerts) == 1
    assert written_alerts[0]["created_at"] == "2026-09-22 03:04:05"
    assert written_alerts[0]["margin_threshold"] == 0.0
    clock.assert_called_once_with()
