"""Explicit operator pauses take priority over seed scope state and early auth wakeups."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import seed_collector, seed_collector_auth, seed_collector_cycle


def _paused_status(signal: str, layout: str) -> dict[str, object]:
    status: dict[str, object] = {
        "paused": True,
        "captcha_solver": {
            "paused": True,
            "manual_required": False,
            "running": False,
            "last_request": {
                "target_url": "https://sf-item.taobao.com/sf_item/3001.htm"
            },
        },
    }
    if signal == "operator_paused":
        status["operator_paused"] = True
    else:
        status["captcha_solver"] = {
            **status["captcha_solver"],  # type: ignore[dict-item]
            "pause_reason": "operator",
        }
    scopes = {
        "seed": {"paused": False, "manual_required": False, "challenge_id": None},
        "detail": {"paused": False, "manual_required": False, "challenge_id": None},
    }
    if layout == "top":
        status["collection_scopes"] = scopes
    else:
        status["captcha_solver"] = {
            **status["captcha_solver"],  # type: ignore[dict-item]
            layout: scopes,
        }
    return status


@pytest.mark.parametrize("owner", [seed_collector_cycle, seed_collector])
@pytest.mark.parametrize("signal", ["operator_paused", "pause_reason"])
@pytest.mark.parametrize("layout", ["top", "collection_scopes", "scopes"])
def test_operator_pause_prevents_seed_claim_when_seed_scope_unpaused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner, signal: str, layout: str
) -> None:
    payload = _paused_status(signal, layout)
    monkeypatch.setattr(
        owner,
        "_collection_pause_state_with_retry",
        lambda _base: seed_collector_auth._normalize_collection_pause_state(payload),
        raising=False,
    )
    if owner is seed_collector_cycle:
        for name in ("_pause_state_blocks_seed_stage", "_write_runtime_summary"):
            monkeypatch.setattr(
                owner, name, getattr(seed_collector_auth, name), raising=False
            )

    def unexpected(*_args, **_kwargs):
        pytest.fail("operator pause must prevent claiming or fetching a seed page")

    repo = SimpleNamespace(
        seed_queue_counts=dict,
        claim_seed_scan_page=unexpected,
        ensure_seed_scan_job=unexpected,
    )
    result = owner.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=10,
            cdp_endpoint="",
            output_dir=tmp_path,
            worker_id="seed-test",
            solver_enabled=True,
            api_base_url="https://example.invalid/api",
        ),
        repository=repo,
        http_session=None,
        browserless_seed_probe=SimpleNamespace(),
    )
    assert result["decision"] == "seed_collection_paused"
    assert result["reason"] == "operator_paused"


@pytest.mark.parametrize("signal", ["operator_paused", "pause_reason"])
def test_operator_pause_does_not_early_wake_seed_auth_backoff(
    monkeypatch: pytest.MonkeyPatch, signal: str
) -> None:
    from tools import seed_collector_wait as owner

    clock = {"now": 0.0}
    monkeypatch.setattr(owner.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _stage: True)
    monkeypatch.setattr(
        owner.worker_lifecycle,
        "wait",
        lambda seconds: clock.update(now=clock["now"] + seconds),
    )
    monkeypatch.setattr(
        owner, "fetch_json", lambda *_args, **_kwargs: _paused_status(signal, "top")
    )
    owner.wait_after_seed_run(
        SimpleNamespace(api_base_url="https://example.invalid/api"),
        [{"decision": "seed_collection_paused"}],
        900,
    )
    assert clock["now"] == 900


def test_global_manual_pause_propagates_to_seed_scope() -> None:
    payload = {
        "paused": True,
        "captcha_solver": {
            "paused": True,
            "global_manual_pause_active": True,
        },
        "collection_scopes": {
            "seed": {"paused": False, "manual_required": False},
        },
    }
    state = seed_collector_auth._normalize_collection_pause_state(payload)
    assert state["paused"] is True
    assert state["reason"] == "captcha_solver_manual_required"
    assert state["captcha_solver"]["manual_required"] is True


def test_paused_loop_does_not_build_browser_context(tmp_path, monkeypatch):
    repo = SimpleNamespace(seed_queue_counts=dict)
    monkeypatch.setattr(seed_collector, "_should_ensure_seed_jobs", lambda *_: False)
    monkeypatch.setattr(seed_collector, "_has_seed_scan_work", lambda _: (True, {}))
    monkeypatch.setattr(seed_collector, "_collection_pause_state_with_retry",
                        lambda _: {"paused": True, "reason": "operator_paused"})
    config = SimpleNamespace(worker_id="test", output_dir=tmp_path, pages_per_run=1,
                             max_runs=1, api_base_url="https://control.invalid")
    result = seed_collector.run_seed_collector_loop(
        config, repository=repo, browserless_seed_probe=None,
        runtime_context_factory=lambda: pytest.fail("paused worker accessed browser"),
        progress_emit_func=lambda _: None)
    assert result["last_decision"] == "seed_collection_paused"
