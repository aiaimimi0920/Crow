"""Seed challenge compaction must not consume another list job's pages."""

import pytest

from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_scope
from tools.test.test_captcha_seed_target_binding import (
    FOREIGN,
    REDIRECTED,
    REQUESTED,
    SOLVER_TARGET,
    selection,
    tab,
)


@pytest.mark.parametrize("foreign", FOREIGN)
@pytest.mark.parametrize("cached", [False, True])
def test_seed_compaction_preserves_other_list_identities(foreign, cached):
    matching = tab("matching", REDIRECTED)
    pages = [
        tab("foreign-one", foreign),
        matching,
        tab("duplicate", REDIRECTED + "&x5step=2"),
        tab("foreign-two", foreign + "&x5secdata=fixture"),
    ]
    solver, actions = selection(pages)
    if cached:
        solver._remember_target_tab(matching)

    assert solver.connect_tab() is True

    assert actions == {
        "connected": ["ws://fixture/matching"],
        "opened": 0,
        "closed": ["duplicate"],
    }


@pytest.mark.parametrize("open_succeeds", [False, True])
def test_only_foreign_seed_challenges_are_not_compacted(open_succeeds):
    pages = [tab(str(index), url) for index, url in enumerate(FOREIGN)]
    solver, actions = selection(pages, open_succeeds=open_succeeds)

    assert solver.connect_tab() is open_succeeds

    assert actions["closed"] == []
    assert actions["opened"] == 1
    assert actions["connected"] == (["ws://fixture/requested"] if open_succeeds else [])


def test_missing_seed_query_cannot_authorize_closing_bound_job_pages():
    solver = CaptchaSolver(target_url="https://sf.taobao.com/list/123.htm")
    closed = []
    solver._close_cdp_target = lambda key: closed.append(key) or True

    assert solver._prune_duplicate_challenge_tabs(
        [tab("bound-one", REDIRECTED), tab("bound-two", REDIRECTED)]
    ) == {"closed": 0, "kept": None}
    assert closed == []


def test_background_scope_compaction_uses_the_same_seed_identity_policy(monkeypatch):
    pages = [
        tab("matching", REDIRECTED),
        tab("duplicate", REDIRECTED + "&x5step=2"),
        tab("foreign", FOREIGN[0]),
    ]
    closed = []
    solver = CaptchaSolver(target_url=SOLVER_TARGET)
    solver._close_cdp_target = lambda key: closed.append(key) or True
    monkeypatch.setattr(pc2_solver_scope, "fetch_json", lambda *args, **kwargs: pages)
    monkeypatch.setattr(
        pc2_solver_scope, "_create_scope_solver", lambda **kwargs: solver
    )
    monkeypatch.setattr(pc2_solver_scope, "node_owns_last_request", lambda *args: True)
    status = {
        "scopes": {
            "seed": {
                "challenge_id": "fixture-challenge",
                "last_request": {"target_url": REQUESTED},
            }
        }
    }

    result = pc2_solver_scope.compact_active_challenge_pages(
        "http://fixture:9223", status, "fixture-node"
    )

    assert result["closed"] == 1
    assert result["scopes"]["seed"] == {"closed": 1, "kept": "matching"}
    assert closed == ["duplicate"]
