"""Existing attempt events retain safe transport/stop failure categories."""

import json
from unittest.mock import Mock

import pytest

from tools import pc2_solver_execution
from tools.solver_observation_evidence import project_line, summarize


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("cdp_unavailable", "cdp_unavailable"),
        ("deadline_exceeded", "deadline_exceeded"),
        ("execution_unavailable", "execution_unavailable"),
        ("slider_endpoint_unconfirmed", "slider_endpoint_unconfirmed"),
        ("private-sentinel", "other"),
    ],
)
def test_real_attempt_producer_keeps_safe_failure_reason_in_report(
    monkeypatch, reason, expected
):
    events = []
    solver = Mock(last_failure_reason=reason)
    solver.solve.return_value = False
    monkeypatch.setattr(
        pc2_solver_execution, "_solver_class", lambda: Mock(return_value=solver)
    )
    monkeypatch.setattr(pc2_solver_execution, "log_event", events.append)

    assert (
        pc2_solver_execution.run_solver_local(
            "http://private-cdp.invalid:9223",
            "https://sf-item.taobao.com/sf_item/123.htm",
        )
        is False
    )
    rows = [
        project_line(f"2026-10-28T02:00:{index:02d}Z " + json.dumps(row), "fixture")
        for index, row in enumerate(events)
    ]
    report = summarize(rows)

    assert report["attempts"][0]["failure_reason"] == expected
    assert report["attempts"][0]["local_success"] is False
    assert report["counts"]["automatic_local_success"] == 0
    assert report["counts"]["auth_confirmed"] == 0
    assert "private-" not in json.dumps(rows) + json.dumps(report)
