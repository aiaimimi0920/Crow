"""A real maintenance navigation and control recovery, with no network access."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from tools import pc2_solver_execution as execution
from tools import pc2_solver_loop_control as control
from tools.test.pc2_maintenance_budget_fixtures import TARGETS, maintenance_probe

CDP = "http://127.0.0.1:9223"


def deferred_recovery(monkeypatch, scope="detail", blank="about:blank"):
    probe = maintenance_probe(monkeypatch, delay=20)
    directory, events = [], []
    create = probe.put.side_effect

    def create_page(*args, **kwargs):
        response = create(*args, **kwargs)
        directory.append(dict(response.json(), url=blank))
        return response

    probe.put.side_effect = create_page
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: deepcopy(directory))
    monkeypatch.setattr(control, "_recent_healthy_auth_snapshot", lambda _: False)
    monkeypatch.setattr(
        control, "check_cdp_browser_for_authenticated_target", lambda *_a: None
    )
    monkeypatch.setattr(control, "log_event", events.append)
    status = {
        "scope": scope,
        "challenge_id": "owned-generation",
        "paused": True,
        "running": False,
        "manual_required": False,
        "last_request": {"node_id": "pc2", "target_url": TARGETS[scope]},
    }

    def recover(pending=None):
        args = (
            "http://nas.invalid/api",
            CDP,
            status,
            [status["last_request"]["target_url"]],
            "pc2",
            0,
        )
        return control.recover_stale_pause(
            *args, **({"last_probe_target": pending} if pending else {})
        )

    # Any second creation in an invalid-identity test is a synthetic successful
    # open, never a replay through the same mock socket and its old CDP replies.
    def permit_new_open():
        opened = Mock(return_value={"id": "replacement", "url": TARGETS[scope]})
        monkeypatch.setattr(execution, "open_maintenance_target", opened)
        return opened

    return SimpleNamespace(
        probe=probe,
        directory=directory,
        events=events,
        status=status,
        recover=recover,
        permit_new_open=permit_new_open,
    )
