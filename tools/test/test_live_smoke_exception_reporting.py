"""Synthetic failures stay private in smoke artifacts, receipts and stdout."""

import json
from types import SimpleNamespace

import pytest
import requests

from src import llm_helper
from tools import live_batch_smoke
from tools import live_smoke_runtime as runtime
from tools.live_smoke_context import LiveSmokeConfig
from tools.test.analysis_module_b_integration_test_context import _write_raw_item
from tools.test.seed_collector_test_context import _FakeProbe

pytestmark = pytest.mark.security
PRIVATE = "synthetic-private-token"
ENDPOINT = f"https://user:{PRIVATE}@private.invalid/?token={PRIVATE}"


def _fail_with_chain(*_args, **_kwargs):
    try:
        raise ValueError(PRIVATE)
    except ValueError as cause:
        raise RuntimeError(ENDPOINT) from cause


def _assert_private_absent(tmp_path, result, output):
    assert PRIVATE not in json.dumps(result)
    assert PRIVATE not in output
    for path in tmp_path.rglob("*.json"):
        assert PRIVATE not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("failure_stage", ["item", "loop"])
def test_smoke_errors_keep_string_shape_without_raw_exceptions(
    tmp_path, monkeypatch, capsys, failure_stage
):
    config = LiveSmokeConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://auction.example.invalid/list",
        target_success=1,
        max_attempts=1,
        do_risk=False,
        raw_only=True,
    )
    if failure_stage == "loop":
        monkeypatch.setattr(runtime, "run_live_smoke", _fail_with_chain)
        result = runtime.run_loop(config, max_runs=1, interval_seconds=0)
        assert result["exit_codes"] == [1]
    else:
        monkeypatch.setattr(runtime, "_browserless_seed_probe", lambda: object())
        monkeypatch.setattr(runtime, "export_cookies", lambda _: [])
        monkeypatch.setattr(runtime, "build_http", lambda _: object())
        monkeypatch.setattr(runtime, "load_open_browser_pages", lambda _: {})
        monkeypatch.setattr(runtime, "process_item", _fail_with_chain)
        monkeypatch.setattr(
            runtime,
            "collect_list_union",
            lambda *_: {
                "items": [{"id": "synthetic-item", "title": "Test property"}],
                "list_union": {},
                "first_fetch": {"list_item_count": 1},
            },
        )
        assert runtime.run_live_smoke(config) == 1
        result = live_batch_smoke.load_json(tmp_path / "summary.json")
        assert (tmp_path / "synthetic-item.error.json").exists()
        state = live_batch_smoke.load_json(tmp_path / "resume_state.json")
        assert "RuntimeError: runtime_error" in json.dumps(state)
    assert result["errors"][0]["error"] == "RuntimeError: runtime_error"
    assert "tools/live_smoke_runtime.py:" in result["errors"][0]["traceback"]
    _assert_private_absent(tmp_path, result, capsys.readouterr().out)


def test_module_b_adjudication_failure_drops_provider_exception_chain(
    tmp_path, monkeypatch, capsys
):
    item_dir, seed, html = _write_raw_item(tmp_path)
    areas = {"flash": 80, "pro": 81, "grok": 82}
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,grok")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL", "arbiter")
    monkeypatch.setattr(
        llm_helper,
        "extract_auction_data",
        lambda *_args, model=None, **_kwargs: json.dumps({"建筑面积": areas[model]}),
    )
    monkeypatch.setattr(llm_helper, "chat_with_glm", _fail_with_chain)
    result = live_batch_smoke._run_analysis_module_b(
        item_id=seed["id"],
        item_dir=item_dir,
        analysis_text="建筑面积80平方米",
        evidence_text="建筑面积80平方米",
        html=html,
        effective_seed=seed,
        do_risk=False,
        mode="shadow",
    )
    assert result["status"] == "adjudication_failed"
    assert result["candidate_success_count"] == 3
    assert result["error"] == {"type": "RuntimeError", "message": "runtime_error"}
    _assert_private_absent(tmp_path, result, capsys.readouterr().out)


def test_module_b_candidate_receipts_keep_retry_status_without_provider_text(
    tmp_path, monkeypatch, capsys
):
    item_dir, seed, html = _write_raw_item(tmp_path)
    calls = []

    def fail_provider(*_args, model=None, **_kwargs):
        calls.append(model)
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError(ENDPOINT, response=response) from ValueError(PRIVATE)

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,grok")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL", "arbiter")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_ATTEMPTS", "2")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_RETRY_SECONDS", "0")
    monkeypatch.setattr(llm_helper, "extract_auction_data", fail_provider)
    result = live_batch_smoke._run_analysis_module_b(
        item_id=seed["id"],
        item_dir=item_dir,
        analysis_text="建筑面积80平方米",
        evidence_text="建筑面积80平方米",
        html=html,
        effective_seed=seed,
        do_risk=False,
        mode="shadow",
    )
    assert result["status"] == "candidate_partial"
    assert len(calls) == 6
    assert len(result["candidate_errors"]) == 3
    assert all(
        entry["error"] == {"type": "HTTPError", "message": "http_error status=429"}
        for entry in result["candidate_errors"]
    )
    _assert_private_absent(tmp_path, result, capsys.readouterr().out)


def test_list_union_keeps_successful_property_data_and_safe_failure(
    tmp_path, monkeypatch
):
    def fetch(*_args, target_url, **_kwargs):
        if "page=2" in target_url:
            _fail_with_chain()
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(live_batch_smoke, "fetch_list_page", fetch)
    config = LiveSmokeConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        target_url="https://sf.taobao.com/list/50025969__2.htm",
        target_success=1,
        max_attempts=1,
        do_risk=False,
        list_max_pages=3,
        list_delay_seconds=0,
    )
    result = live_batch_smoke.collect_list_union(_FakeProbe, object(), config)
    assert [item["id"] for item in result["items"]] == ["2001", "2002"]
    sources = result["list_union"]["sources"]
    assert sources[0]["list_status"] == 200
    assert sources[1]["error"] == "RuntimeError: runtime_error"
    assert "tools/live_smoke_list.py:" in sources[1]["traceback"]
    assert sources[2]["skipped"] is True
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize("stage", ["list", "keepalive", "close"])
def test_cdp_cleanup_errors_are_safe_and_keep_recovery_behavior(monkeypatch, stage):
    targets = [{"id": "target-1", "type": "page"}, {"id": "target-2", "type": "page"}]
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: targets)

    def get(_endpoint, path, **_kwargs):
        if stage == "list" or path.startswith("/json/close/"):
            _fail_with_chain()
        return response

    monkeypatch.setattr(live_batch_smoke, "_cdp_http_get", get)
    monkeypatch.setattr(
        live_batch_smoke,
        "open_cdp_keepalive_target",
        _fail_with_chain if stage == "keepalive" else lambda *a, **k: "keepalive",
    )
    result = live_batch_smoke.compact_cdp_page_targets_if_needed(ENDPOINT, limit=1)
    assert result["triggered"] is (stage != "list")
    assert result["errors"]
    assert all("RuntimeError: runtime_error" in error for error in result["errors"])
    assert PRIVATE not in json.dumps(result)


def test_browser_probe_failure_logs_safe_error_and_still_falls_back(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        live_batch_smoke, "fetch_open_browser_list_page", _fail_with_chain
    )
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_browser_navigation_list_page",
        lambda *_args: ("fallback", "https://auction.example.invalid/list"),
    )
    assert live_batch_smoke.fetch_browser_list_page(
        ENDPOINT, "https://auction.example.invalid/list"
    ) == ("fallback", "https://auction.example.invalid/list")
    output = capsys.readouterr().out
    assert "RuntimeError: runtime_error" in output
    assert PRIVATE not in output
