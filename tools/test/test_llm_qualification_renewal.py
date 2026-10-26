"""Only configured routes renew; old qualifications never authorize discovery."""

import time

from src.llm_qualification_pool import QUALIFICATION_TTL
from tools.test.test_llm_qualification_pool import make_pool


def seed_records(pool, records, **state_fields):
    pool.store.change(lambda state: state.update(models=records, **state_fields))


def expired_row(score=5, *, age=QUALIFICATION_TTL + 60, blocked_until=0):
    return {
        "score": score,
        "checked_at": time.time() - age,
        "elapsed": 1,
        "blocked_until": blocked_until,
    }


def test_expired_preferred_model_renews_without_unconfigured_probe(tmp_path):
    pool = make_pool(tmp_path, {"preferred": 5, "new-alias": 5})
    pool.config["models"] = ["preferred"]
    old = expired_row()
    seed_records(pool, {"preferred": old})
    pool.session.failed.add("new-alias")

    assert pool.available() == []
    assert pool.ensure() == ["preferred"]
    assert pool.session.calls == ["preferred"] * 5
    state = pool.store.snapshot()
    assert state["models"]["preferred"]["matches"] == [1] * 5
    assert state["models"]["preferred"]["checked_at"] > old["checked_at"]
    assert not state.get("cooldown_until")
    assert state["next_scan"] > time.time() + 115


def test_configured_order_is_not_overridden_by_historical_qualification(tmp_path):
    pool = make_pool(tmp_path, {"last-good": 4, "new-alias": 5, "old-bad": 0})
    pool.config["models"] = ["last-good", "new-alias", "old-bad"]
    seed_records(
        pool,
        {
            "last-good": expired_row(4),
            "old-bad": expired_row(0, age=QUALIFICATION_TTL * 2),
        },
    )
    pool.session.failed.add("new-alias")

    assert pool.ensure() == ["last-good"]
    assert pool.session.calls == ["last-good"] * 5 + ["new-alias"]
    assert pool.store.snapshot()["models"]["old-bad"]["score"] == 0


def test_due_explicit_preferences_keep_configured_order_before_renewal(tmp_path):
    pool = make_pool(tmp_path, {"first": 3, "second": 4, "last-good": 5})
    pool.config["models"] = ["first", "second"]
    seed_records(
        pool,
        {
            "first": expired_row(0, age=901),
            "second": expired_row(0, age=902),
            "last-good": expired_row(),
        },
    )

    selected = pool.ensure()
    assert pool.session.calls == ["first"] * 5 + ["second"] * 5
    assert "first" not in selected
    assert selected == ["second"]
    assert (
        pool.store.snapshot()["models"]["last-good"]["checked_at"]
        < time.time() - QUALIFICATION_TTL
    )


def test_fresh_or_blocked_preference_is_not_retested_early(tmp_path):
    pool = make_pool(tmp_path, {"fresh": 5, "blocked": 5, "new-alias": 4})
    pool.config["models"] = ["fresh", "blocked"]
    records = {
        "fresh": expired_row(age=30),
        "blocked": expired_row(blocked_until=time.time() + 900),
    }
    seed_records(pool, records)

    assert pool.ensure() == ["fresh"]
    assert pool.session.calls == []
    state = pool.store.snapshot()
    assert state["models"]["fresh"] == records["fresh"]
    assert state["models"]["blocked"] == records["blocked"]


def test_renewal_never_bypasses_shared_account_cooldown(tmp_path):
    pool = make_pool(tmp_path, {"preferred": 5})
    pool.config["models"] = ["preferred"]
    seed_records(pool, {"preferred": expired_row()})
    pool.store.cool_down(3600)
    before = pool.store.snapshot()

    assert pool.ensure() == []
    assert not pool.session.calls
    assert pool.store.snapshot() == before


def test_explicit_order_wins_over_unseen_model_priority(tmp_path):
    pool = make_pool(tmp_path, {"old-bad": 0, "new-alias": 4})
    seed_records(pool, {"old-bad": expired_row(0)})

    assert pool.ensure() == ["new-alias"]
    assert pool.session.calls == ["old-bad"] * 5 + ["new-alias"] * 5
