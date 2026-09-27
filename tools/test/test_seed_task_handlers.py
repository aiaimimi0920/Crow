"""Seed route ownership and saved callback behavior."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def host():
    from src import server

    return server


def test_seed_methods_are_native_and_keep_handler_descriptor(host):
    from src import seed_task_handlers

    handler = object.__new__(host.DataHandler)
    for name in ("_post_seed_next_task", "_post_seed_progress"):
        method = getattr(handler, name)
        assert method.__self__ is handler
        assert method.__func__ is getattr(host, name)
        assert method.__module__ == seed_task_handlers.__name__
        assert getattr(host._CONTEXT, name) is getattr(host, name)


@pytest.mark.parametrize(
    "payload, session",
    [
        ({}, "default"),
        ({"session_id": " padded "}, " padded "),
        ({"session_id": "x" * 128}, "x" * 128),
    ],
)
def test_saved_claim_reads_current_service_pause_and_preserves_session(
    host, monkeypatch, payload, session
):
    claim = object.__new__(host.DataHandler)._post_seed_next_task
    service = SimpleNamespace(next_task=Mock(return_value={"task": None}))
    monkeypatch.setattr(host, "_read_json_body", lambda handler: (True, payload))
    monkeypatch.setattr(host, "_seed_collection_service", lambda: service)
    monkeypatch.setattr(
        host, "_collection_scope_effectively_paused", lambda scope: scope == "seed"
    )
    responses = []
    monkeypatch.setattr(
        host.DataHandler, "send_json", lambda self, data: responses.append(data)
    )
    claim()
    service.next_task.assert_called_once_with(session, paused=True)
    assert responses == [{"task": None}]


def test_progress_passes_original_generic_task_payload(host, monkeypatch):
    report = host._post_seed_progress
    payload = {
        "task_key": "source:page:3",
        "has_next": False,
        "zero_bid_detected": True,
    }
    service = SimpleNamespace(report_progress=Mock(return_value={"done": True}))
    monkeypatch.setattr(host, "_read_json_body", lambda handler: (True, payload))
    monkeypatch.setattr(host, "_seed_collection_service", lambda: service)
    handler = SimpleNamespace(send_json=Mock())
    report(handler)
    assert service.report_progress.call_args.args[0] is payload
    handler.send_json.assert_called_once_with({"done": True})


@pytest.mark.parametrize("method", ["_post_seed_next_task", "_post_seed_progress"])
def test_rejected_body_does_not_construct_service(host, monkeypatch, method):
    service = Mock()
    monkeypatch.setattr(host, "_read_json_body", lambda handler: (False, None))
    monkeypatch.setattr(host, "_seed_collection_service", service)
    getattr(host, method)(SimpleNamespace())
    service.assert_not_called()
