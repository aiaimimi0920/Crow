"""Exercise observer lifecycle with synthetic Docker output and clock."""

import json
import sys
from types import SimpleNamespace

import pytest

from tools import solver_observation as monitor
from tools.solver_observation_evidence import summarize
from tools.test.test_solver_observation import event, payload, success


def test_completed_attempt_is_immutable():
    rows = success() + [event("local_solver_end", 8, success=False)]
    assert summarize(rows)["counts"]["automatic_local_success"] == 1


def test_missing_link_is_not_guessed():
    rows = success() + [
        event(
            "auth_complete_result",
            4,
            result={"confirmed": True, "result": payload(), "state": {}},
        )
    ]
    counts = summarize(rows)["counts"]
    assert counts["automatic_auth_confirmations"] == 1
    assert counts["auth_confirmed"] == 0


def test_restart_cannot_complete_old_drag():
    rows = success()[:2] + [{"kind": "observer_restart_boundary"}] + success()[2:]
    assert summarize(rows)["counts"]["automatic_local_success"] == 0


@pytest.mark.parametrize("bad", [[], {}, 123])
def test_malformed_kind_is_ignored(bad):
    from tools.solver_observation_evidence import project_line

    assert (
        project_line("2026-10-06T12:00:00Z " + json.dumps({"kind": bad}), "a") is None
    )


@pytest.fixture
def fake_host(monkeypatch, tmp_path):
    clock = [1791288000.0]
    monkeypatch.setattr(monitor.time, "time", lambda: clock[0])
    monkeypatch.setattr(
        monitor.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setitem(
        sys.modules,
        "fcntl",
        SimpleNamespace(flock=lambda *_: None, LOCK_EX=1, LOCK_NB=2),
    )
    identity = {
        "id": "container-a",
        "started_at": monitor.utc(clock[0] - 100),
        "project": "test",
        "service": "solver",
        "image": "image-a",
    }
    monkeypatch.setattr(monitor, "inspect_container", lambda _: dict(identity))
    args = SimpleNamespace(
        output=tmp_path,
        container="test",
        source_revision="test-revision",
        hours=2 / 3600,
        interval=1,
    )
    calls = []

    def docker(*parts, **_options):
        calls.append(parts)
        if parts[0] == "exec":
            return SimpleNamespace(stdout='{"captured_count":10}', stderr="")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(monitor, "docker", docker)
    return args, calls, clock, identity, docker


def test_window_finishes_and_final_report_can_be_reconciled(fake_host):
    args, calls, _, _, _ = fake_host
    monitor.observe(args)
    report = json.loads((args.output / "report.json").read_text())
    assert report["window_finished"] and report["logs_read_through_deadline"]
    assert report["counts"]["started"] == 0
    before = len(calls)
    monitor.observe(args)
    assert len(calls) == before
    assert json.loads((args.output / "report.json").read_text())["window_finished"]


def test_failed_read_retries_original_cursor(fake_host, monkeypatch):
    args, calls, _, _, original = fake_host
    failed = [False]

    def docker(*parts, **options):
        if parts[0] == "logs" and not failed[0]:
            calls.append(parts)
            failed[0] = True
            raise OSError("private credential must not persist")
        return original(*parts, **options)

    monkeypatch.setattr(monitor, "docker", docker)
    monitor.observe(args)
    reads = [c for c in calls if c[0] == "logs"]
    assert (
        reads[0][reads[0].index("--since") + 1]
        == reads[1][reads[1].index("--since") + 1]
    )
    report = (args.output / "report.json").read_text()
    assert "log_read_gap" in report and "private credential" not in report


def test_old_container_tail_read_on_replacement(fake_host, monkeypatch):
    args, calls, clock, identity, original = fake_host
    initial = clock[0]

    def docker(*parts, **options):
        if parts[0] == "exec":
            identity.update(id="container-b", started_at=monitor.utc(initial + 0.5))
        return original(*parts, **options)

    monkeypatch.setattr(monitor, "docker", docker)
    monitor.observe(args)
    reads = [c[-1] for c in calls if c[0] == "logs"]
    assert reads[:3] == ["container-a", "container-a", "container-b"]
    events = monitor.load_rows(args.output / "events.jsonl")
    assert any(e["kind"] == "observer_restart_boundary" for e in events)
