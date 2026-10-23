"""Pending restart receipts serialize ahead of all new mutation work."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from tools import pc2_collection_controller as coordinator


@pytest.mark.parametrize("response", [None, 409, 401, 503])
@pytest.mark.parametrize("settings_pending", [False, True])
def test_pending_restart_delivered_before_settings_or_watchdogs(
    tmp_path,
    monkeypatch,
    response,
    settings_pending,
):
    monkeypatch.setattr(coordinator, "operation_lock", lambda _root: nullcontext())
    settings = SimpleNamespace(journal=tmp_path / "settings-receipt.json", step=Mock())
    if settings_pending:
        settings.journal.write_text("{}", encoding="utf-8")
    error = (
        HTTPError("https://fixture.invalid", response, "synthetic", {}, None)
        if response
        else None
    )
    client = SimpleNamespace(post=Mock(side_effect=error))
    restart = coordinator.RestartController(client, Mock(), tmp_path)
    restart.persist({"request_id": "fixture", "claim": "a" * 64, "result": "restarted"})
    watchdogs = [SimpleNamespace(step=Mock()) for _ in range(3)]
    if response in (401, 503):
        with pytest.raises(HTTPError):
            coordinator.step(tmp_path, settings, restart, *watchdogs)
        assert restart.journal.exists()
    else:
        coordinator.step(tmp_path, settings, restart, *watchdogs)
        assert not restart.journal.exists()
    settings.step.assert_not_called()
    restart.engine.inspect.assert_not_called()
    for watchdog in watchdogs:
        watchdog.step.assert_not_called()
    assert client.post.call_count == 1
