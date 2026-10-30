"""Fresh failure-side ownership checks never select an unrelated active scope."""

from copy import deepcopy

import pytest

from tools.pc2_solver_failure_guard import failure_mutation_block_reason as blocked

CDP = "http://127.0.0.1:9223"
TARGETS = {
    "seed": "https://sf.taobao.com/list/50025969__2.htm?page=2&location_code=31",
    "detail": "https://sf-item.taobao.com/sf_item/123.htm",
}


def active(scope):
    return {
        "scope": scope,
        "challenge_id": "owned",
        "last_status": "running",
        "paused": True,
        "manual_required": False,
        "running": False,
        "last_request": {"target_url": TARGETS[scope], "node_id": "pc2"},
    }


@pytest.fixture(autouse=True)
def enable_fixture(monkeypatch):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("field", ["scopes", "collection_scopes"])
def test_exact_scope_wins_over_unrelated_aggregate_and_oldest_challenge(scope, field):
    started = active(scope)
    other = "detail" if scope == "seed" else "seed"
    latest = active(other)
    latest[field] = {
        other: {**active(other), "challenge_id": "older", "first_seen_epoch": 1},
        scope: {**active(scope), "first_seen_epoch": 99},
    }
    before = deepcopy(latest)

    assert blocked(started, latest, TARGETS[scope], CDP, "pc2") is None
    assert latest == before


@pytest.mark.parametrize("scope", ["seed", "detail"])
def test_legacy_single_scope_and_url_hint_remain_compatible(scope):
    started = active(scope)
    latest = active(scope)
    for status in (started, latest):
        status.pop("scope")
        status["challenge_id"] = None

    assert blocked(started, latest, TARGETS[scope], CDP, "pc2") is None


def test_seed_query_order_and_transient_challenge_tokens_preserve_identity():
    started = active("seed")
    latest = active("seed")
    latest["last_request"]["target_url"] = (
        "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish"
        "?location_code=31&page=2&x5secdata=private-fixture"
    )

    assert blocked(started, latest, TARGETS["seed"], CDP, "pc2") is None


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize("change", ["identity", "target", "owner"])
def test_old_snapshot_cannot_authorize_mutating_changed_legacy_request(scope, change):
    started = active(scope)
    latest = active(scope)
    if change == "identity":
        latest["challenge_id"] = "new"
    elif change == "target":
        latest["last_request"]["target_url"] = (
            TARGETS[scope].replace("page=2", "page=3").replace("123.htm", "456.htm")
        )
    else:
        latest["last_request"].update(node_id="pc1", cdp_endpoint=CDP)

    assert blocked(started, latest, TARGETS[scope], CDP, "pc2")


@pytest.mark.parametrize(
    "latest",
    [
        None,
        [],
        {},
        {"error": "offline"},
        {"scopes": {}},
        {"scopes": None},
        {"scopes": {"detail": {"error": "offline"}}},
    ],
)
def test_unavailable_or_malformed_scope_is_not_authority(latest):
    assert blocked(active("detail"), latest, TARGETS["detail"], CDP, "pc2")


@pytest.mark.parametrize("flag", ["force_reset_required", "force_unlock_flag_exists"])
def test_explicit_reset_or_unlock_blocks_stale_cleanup(flag):
    started = active("detail")
    latest = {**started, flag: True}
    assert blocked(started, latest, TARGETS["detail"], CDP, "pc2")


def test_scoped_idle_cannot_erase_global_nas_running_guard():
    started = active("detail")
    latest = {
        **started,
        "running": True,
        "scopes": {"detail": {**started, "running": False}},
    }
    assert (
        blocked(started, latest, TARGETS["detail"], CDP, "pc2") == "nas_solver_running"
    )


def test_new_id_cannot_be_adopted_by_an_unbound_legacy_attempt():
    started = active("detail")
    started["challenge_id"] = None
    assert (
        blocked(started, active("detail"), TARGETS["detail"], CDP, "pc2")
        == "request_identity_changed"
    )


def test_explicit_legacy_other_scope_cannot_authorize_old_attempt():
    assert (
        blocked(active("detail"), active("seed"), TARGETS["detail"], CDP, "pc2")
        == "request_scope_changed"
    )
