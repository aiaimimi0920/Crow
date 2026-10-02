"""A seed-only pause must not stall a confirmed resumed detail worker."""

from types import SimpleNamespace

import pytest

from tools import detail_worker_wait as owner


@pytest.mark.parametrize("seed_manual", [False, True])
def test_seed_only_pause_wakes_confirmed_clear_detail_scope(monkeypatch, seed_manual):
    clock = {"now": 0, "polls": 0}
    monkeypatch.setattr(owner.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _: True)

    def wait(seconds):
        clock["now"] += seconds

    def fetch(*args, **kwargs):
        clock["polls"] += 1
        return {
            "paused": True,
            "collection_scopes": {
                "seed": {"paused": True, "manual_required": seed_manual},
                "detail": {
                    "paused": False,
                    "manual_required": False,
                    "challenge_id": None,
                },
            },
        }

    monkeypatch.setattr(owner.worker_lifecycle, "wait", wait)
    monkeypatch.setattr(owner, "fetch_json", fetch)
    owner.wait_after_detail_batch(
        SimpleNamespace(analysis_only=False, api_base_url="https://nas/api"),
        {"results": [{"reason": "detail_challenge_page"}]},
        900,
    )
    assert clock == {"now": 30, "polls": 1}
