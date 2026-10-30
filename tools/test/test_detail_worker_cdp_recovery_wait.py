"""Only confirmed transport recovery may shorten the CDP outage backoff."""

from types import SimpleNamespace

import pytest

from tools import detail_worker_wait as owner


@pytest.fixture
def state(monkeypatch):
    state = SimpleNamespace(now=0, waits=[], polls=0, probes=[])

    def wait(seconds):
        state.waits.append(seconds)
        state.now += seconds

    def fetch(*args, **kwargs):
        state.polls += 1
        return {
            "paused": False,
            "collection_scopes": {
                "detail": {
                    "paused": False,
                    "manual_required": False,
                    "challenge_id": None,
                }
            },
        }

    def probe(endpoint, *, timeout_seconds):
        state.probes.append((endpoint, timeout_seconds))
        return True

    monkeypatch.setattr(owner.time, "monotonic", lambda: state.now)
    monkeypatch.setattr(owner.worker_lifecycle, "wait", wait)
    monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _: True)
    monkeypatch.setattr(owner, "fetch_json", fetch)
    monkeypatch.setattr(owner, "cdp_metadata_recovered", probe)
    return state


def config(**overrides):
    values = {
        "analysis_only": False,
        "api_base_url": "https://nas.invalid/api",
        "cdp_endpoint": "http://cdp.invalid:9224",
    }
    return SimpleNamespace(**(values | overrides))


def outage():
    return {
        "results": [
            {
                "decision": "detail_item_retryable_failure",
                "reason": "detail_cdp_unreachable",
                "capture_failure": {
                    "operation": "connect_over_cdp_bounded_reconnect",
                    "cause": {
                        "type": "RuntimeError",
                        "message": "runtime_error",
                        "endpoint_unhealthy": True,
                    },
                },
            }
        ]
    }


def test_confirmed_endpoint_recovery_wakes_without_site_or_driver(monkeypatch, state):
    receipt = owner.wait_after_detail_batch(config(), outage(), 900)
    assert state.now == 30
    assert state.polls == 1
    assert state.probes == [("http://cdp.invalid:9224", 5)]
    assert receipt == {
        "requested_wait_seconds": 900,
        "actual_wait_seconds": 30,
        "status_poll_count": 1,
        "cdp_poll_count": 1,
        "wait_exit": "cdp_resumed",
    }


def test_unhealthy_endpoint_keeps_wait_then_recovers(monkeypatch, state):
    monkeypatch.setattr(
        owner,
        "cdp_metadata_recovered",
        lambda *args, **kwargs: state.now >= 90,
        raising=False,
    )
    receipt = owner.wait_after_detail_batch(config(), outage(), 900)
    assert state.waits == [30, 30, 30]
    assert receipt["wait_exit"] == "cdp_resumed"
    assert receipt["cdp_poll_count"] == 3


@pytest.mark.parametrize(
    "status",
    [
        {},
        {"paused": False},
        {"operator_paused": True},
        {"paused": True, "reason": "operator_paused"},
        {"paused": False, "collection_scopes": {"detail": {"paused": True}}},
    ],
)
def test_unknown_paused_or_operator_state_never_probes_cdp(monkeypatch, state, status):
    monkeypatch.setattr(owner, "fetch_json", lambda *a, **kw: status)
    receipt = owner.wait_after_detail_batch(config(), outage(), 90)
    assert state.now == 90
    assert state.probes == []
    assert receipt["wait_exit"] == "deadline_elapsed"


def test_seed_only_pause_does_not_block_clear_detail_recovery(monkeypatch, state):
    status = owner.fetch_json("")
    status["paused"] = True
    status["collection_scopes"]["seed"] = {"paused": True}
    monkeypatch.setattr(owner, "fetch_json", lambda *a, **kw: status)
    assert owner.wait_after_detail_batch(config(), outage(), 900)["wait_exit"] == (
        "cdp_resumed"
    )


@pytest.mark.parametrize("field", ["paused", "manual_required", "challenge_id"])
def test_active_detail_state_never_wakes(monkeypatch, state, field):
    status = owner.fetch_json("")
    status["collection_scopes"]["detail"][field] = True
    monkeypatch.setattr(owner, "fetch_json", lambda *a, **kw: status)
    receipt = owner.wait_after_detail_batch(config(), outage(), 90)
    assert receipt["wait_exit"] == "deadline_elapsed"
    assert not state.probes


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item["capture_failure"]["cause"].pop("endpoint_unhealthy"),
        lambda item: item["capture_failure"]["cause"].update(endpoint_unhealthy=1),
        lambda item: item["capture_failure"]["cause"].update(type="TimeoutError"),
        lambda item: item["capture_failure"].update(
            operation="detail_browser_capture_deadline"
        ),
        lambda item: item.update(reason="detail_browser_proxy_unavailable"),
        lambda item: item.update(reason="exception"),
        lambda item: item.update(decision="detail_item_completed"),
    ],
)
def test_ambiguous_failure_does_not_shorten_backoff(monkeypatch, state, mutation):
    result = outage()
    mutation(result["results"][0])
    receipt = owner.wait_after_detail_batch(config(), result, 900)
    assert state.waits == [900]
    assert not state.probes and not state.polls
    assert receipt["wait_exit"] == "wait_returned"


@pytest.mark.parametrize(
    "overrides",
    [
        {"analysis_only": True},
        {"api_base_url": ""},
        {"cdp_endpoint": ""},
        {"cdp_endpoint": "ws://cdp.invalid/devtools/browser/fixture"},
    ],
)
def test_unrelated_or_unprobeable_config_keeps_original_wait(state, overrides):
    receipt = owner.wait_after_detail_batch(config(**overrides), outage(), 900)
    assert state.waits == [900]
    assert not state.probes
    assert receipt["wait_exit"] == "wait_returned"


def test_actual_challenge_wait_is_not_shortened_by_transport_marker(monkeypatch, state):
    result = outage()
    result["results"].append({"reason": "detail_challenge_page"})
    monkeypatch.setattr(owner, "fetch_json", lambda *a, **kw: {})
    owner.wait_after_detail_batch(config(), result, 90)
    assert state.now == 90
    assert not state.probes


def test_shutdown_before_and_during_wait_does_not_probe(monkeypatch, state):
    monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _: state.now == 0)
    receipt = owner.wait_after_detail_batch(config(), outage(), 900)
    assert receipt["wait_exit"] == "stopping"
    assert not state.probes and not state.polls


def test_probe_time_is_bounded_by_remaining_wait(monkeypatch, state):
    def fetch(*args, **kwargs):
        state.now += 4
        return {
            "paused": False,
            "collection_scopes": {
                "detail": {
                    "paused": False,
                    "manual_required": False,
                    "challenge_id": None,
                }
            },
        }

    monkeypatch.setattr(owner, "fetch_json", fetch)
    receipt = owner.wait_after_detail_batch(config(), outage(), 35)
    assert state.probes == [("http://cdp.invalid:9224", 1)]
    assert receipt["actual_wait_seconds"] == 34


def test_shutdown_during_status_read_never_probes(monkeypatch, state):
    original = owner.fetch_json

    def fetch(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _: False)
        return result

    monkeypatch.setattr(owner, "fetch_json", fetch)
    receipt = owner.wait_after_detail_batch(config(), outage(), 900)
    assert receipt["wait_exit"] == "stopping"
    assert not state.probes


def test_outage_never_polls_after_wait_deadline(monkeypatch, state):
    monkeypatch.setattr(owner, "cdp_metadata_recovered", lambda *a, **kw: False)
    receipt = owner.wait_after_detail_batch(config(), outage(), 90)
    assert state.now == 90
    assert receipt["status_poll_count"] == 2
    assert receipt["wait_exit"] == "deadline_elapsed"
