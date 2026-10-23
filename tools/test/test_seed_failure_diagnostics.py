"""Per-page evidence must survive summary replacement without leaking payloads."""

import json

import pytest

from tools import seed_collector
from tools.seed_collector_diagnostics import record_seed_exception
from tools.test.seed_collector_test_context import _FakeProbe, _make_repo


@pytest.mark.parametrize("broken_stdout", [False, True])
def test_failure_evidence_survives_summary_replacement(tmp_path, monkeypatch, capsys, broken_stdout):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(seed_collector, "_collection_pause_state_with_retry", lambda _: {})
    monkeypatch.setattr(seed_collector, "resolve_runtime_user_agent", lambda _: "test")

    def fail(*args, **kwargs):
        raise RuntimeError("private-url?token=secret-cookie")

    monkeypatch.setattr(seed_collector, "fetch_list_page", fail)
    if broken_stdout:
        def fail_print(*args, **kwargs):
            raise BrokenPipeError("closed output")
        monkeypatch.setattr("builtins.print", fail_print)
    config = seed_collector.SeedCollectorConfig(
        job_key="diagnostic-test", province="", city="", district="",
        location_code="371602", category="50025969",
        sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:test"),
        max_page=83, cdp_endpoint="http://127.0.0.1:9224",
        output_dir=tmp_path, worker_id="diagnostic-test",
    )
    try:
        result = seed_collector.run_seed_collector_once(
            config, repository=repo, http_session=object(), browserless_seed_probe=_FakeProbe,
        )
        assert result["reason"] == "exception"
        seed_collector._write_runtime_summary(
            tmp_path, seed_collector._seed_run_progress_event(1, [result])
        )
        raw = (tmp_path / "seed_collector_last_failure.json").read_text(encoding="utf-8")
        saved = json.loads(raw)
        assert saved["stage"] == "fetch_list_page"
        assert saved["error"] == "RuntimeError: runtime_error"
        assert "tools/seed_collector_cycle.py:" in saved["traceback"]
        assert saved["observed_at_epoch"] > 0
        output = capsys.readouterr().out
        assert (output == "") if broken_stdout else (json.loads(output) == saved)
        assert "secret-cookie" not in raw and "private-url" not in raw
        retry = repo.claim_seed_scan_page("retry", lease_seconds=30)
        assert retry and retry["page"] == 1
        assert repo.seed_queue_counts()["seed_item_pending_detail"] == 0
    finally:
        repo.engine.dispose()


def test_failed_diagnostic_write_still_emits_safe_event(tmp_path, capsys):
    record_seed_exception(tmp_path / "missing", ValueError("secret"), stage="fetch_list_page")
    event = json.loads(capsys.readouterr().out)
    assert event["error"] == "ValueError: invalid_value"
    assert "secret" not in json.dumps(event)
