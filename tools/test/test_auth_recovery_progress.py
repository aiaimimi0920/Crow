"""Recovery counters preserve progress across archival stage transitions."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.auth_recovery_progress import captured_detail_count, pending_detail_count


def repository(counts):
    return SimpleNamespace(enabled=True, seed_queue_counts=lambda: counts)


def test_archival_transitions_do_not_invent_capture_progress():
    counts = {"seed_item_raw_detail_captured": 4, "seed_item_pending_detail": 2}
    repo = repository(counts)
    assert captured_detail_count(repo) == 4
    assert pending_detail_count(repo) == 2
    for stage in (
        "analysis_in_progress",
        "analysis_failed",
        "analysis_blocked",
        "detail_completed",
    ):
        counts["seed_item_raw_detail_captured"] -= 1
        counts["seed_item_" + stage] = 1
        assert captured_detail_count(repo) == 4
        assert pending_detail_count(repo) == 2
    counts["seed_item_pending_detail"] -= 1
    counts["seed_item_in_progress"] = 1
    assert pending_detail_count(repo) == 2
    assert captured_detail_count(repo) == 4


@pytest.mark.parametrize(
    "counts",
    [
        None,
        [],
        "invalid",
        {"seed_item_raw_detail_captured": "bad", "seed_item_pending_detail": "bad"},
    ],
)
def test_invalid_repository_counts_preserve_unknown_capture(counts):
    assert captured_detail_count(repository(counts)) is None
    assert pending_detail_count(repository(counts)) == 0


def test_disabled_repository_is_not_queried():
    def query():
        pytest.fail("disabled repository must not be queried")

    repo = SimpleNamespace(enabled=False, seed_queue_counts=query)
    assert captured_detail_count(repo) is None
    assert pending_detail_count(repo) == 0


def test_repository_failure_preserves_unknown_capture():
    def query():
        raise RuntimeError("synthetic storage failure")

    repo = SimpleNamespace(enabled=True, seed_queue_counts=query)
    assert captured_detail_count(repo) is None
    assert pending_detail_count(repo) == 0


def test_facade_uses_current_repository(monkeypatch):
    from src import server

    first = repository({"seed_item_raw_detail_captured": 3})
    second = repository({"seed_item_detail_completed": 7, "seed_item_in_progress": 2})
    read_captured = server._solver_detail_captured_count
    native = replace(read_captured.__self__, repository=lambda: first)
    monkeypatch.setattr(server, "DB_REPOSITORY", second)
    assert native._solver_detail_captured_count() == 3
    assert read_captured() == 7
    assert server._nas_auth_recovery_pending_detail_count() == 2
    monkeypatch.setattr(server, "DB_REPOSITORY", first)
    assert read_captured() == 3


def test_watchdog_keeps_polling_after_error_with_current_providers(monkeypatch, caplog):
    from src import server

    watch = server.nas_auth_recovery_watchdog_thread
    delays = []

    class StopWatchdog(BaseException):
        pass

    def failed_sample():
        raise RuntimeError("synthetic sampling error")

    def sleep(seconds):
        delays.append(seconds)
        if len(delays) == 2:
            raise StopWatchdog
        monkeypatch.setattr(server, "NAS_AUTH_RECOVERY_POLL_SECONDS", 5)
        monkeypatch.setattr(
            server,
            "_sample_nas_auth_recovery",
            lambda: {"active": {"status": "requested", "recovery_id": "next-recovery"}},
        )

    monkeypatch.setattr(server, "_sample_nas_auth_recovery", failed_sample)
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY_POLL_SECONDS", 2)
    monkeypatch.setattr(server, "time", SimpleNamespace(sleep=sleep))
    with pytest.raises(StopWatchdog):
        watch()
    assert delays == [2, 5]
    assert "Watchdog sample failed" in caplog.text
    assert "next-recovery" in caplog.text
