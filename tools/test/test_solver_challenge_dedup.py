"""Repeated reports must not demote an active manual-authentication latch."""

import logging

import pytest

from src.runtime_state import RuntimeState
from src.solver_challenge_creation import ChallengeCreation


@pytest.mark.parametrize("restored", [False, True])
def test_repeated_challenge_preserves_manual_state(restored):
    runtime = RuntimeState()
    state = {
        "challenge_id": "existing",
        "first_seen_epoch": 10,
        "pause_started_epoch": 10,
        "paused": True,
        "pause_reason": "manual_required",
        "manual_required": True,
        "manual_only": True,
        "last_status": "manual_required",
        "last_failure_reason": "repeated_solver_failures",
    }
    published = []
    pauses = []
    if not restored:
        runtime.control.set_scope("detail", state)
    creation = ChallengeCreation(
        runtime=runtime,
        build_request=dict,
        request_scope=lambda _: "detail",
        bind_root=lambda: None,
        read_scope=lambda _: dict(state) if restored else {},
        read_legacy=dict,
        persist_scope=lambda scope, value: published.append(dict(value)),
        persist_legacy=lambda *_: None,
        owner_key=lambda _: ("pc2", "browser"),
        request_key=lambda _: ("pc2", "browser", "detail"),
        effectively_paused=lambda: True,
        set_pause=lambda paused, reason, **kwargs: pauses.append(reason),
        clock=lambda: 100,
        new_id=lambda: "unexpected",
        logger=logging.getLogger(__name__),
    )
    with runtime.lock:
        assert creation.begin_locked({"scope": "detail"}) == "existing"
    for key, value in state.items():
        assert published[-1][key] == value
    assert pauses == ["manual_required"]
