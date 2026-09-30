"""Exercise public worker facades, including their cloned-function globals."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import cdp_cookie_transport as transport
from src.project_environment import EnvironmentAliasConflict
from tools import detail_worker, live_batch_smoke, seed_collector
from tools.worker_lifecycle import WorkerLifecycle


def configure(monkeypatch, prefix, **settings):
    for key, value in settings.items():
        for spelling in ("CROW", "FAPAI"):
            monkeypatch.delenv(spelling + "_" + key, raising=False)
            if prefix in (spelling, "BOTH"):
                monkeypatch.setenv(spelling + "_" + key, value)


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_worker_public_cli_configuration_preserves_aliases(
    monkeypatch, tmp_path, prefix
):
    configure(
        monkeypatch,
        prefix,
        OUTPUT_DIR=str(tmp_path),
        CDP_ENDPOINT="http://example.invalid:9223",
        DETAIL_ARCHIVE_ROOT=str(tmp_path / "archive"),
        DETAIL_TARGET_SUCCESS="7",
        DETAIL_LOOP="yes",
        SEED_MAX_PAGE="4",
        SEED_JOB_KEY="test-seed",
        SEED_SOURCE_URL_TEMPLATE="https://example.invalid/{page}",
        CAPTCHA_SOLVER_ENABLED="1",
        MANUAL_CHALLENGE_REPORTING="true",
    )
    detail, loop = detail_worker.config_from_env_and_args([])
    seed, _ = seed_collector.config_from_env_and_args([])
    assert detail.output_dir == seed.output_dir == tmp_path
    assert detail.cdp_endpoint == seed.cdp_endpoint == "http://example.invalid:9223"
    assert detail.detail_archive_root == tmp_path / "archive"
    assert detail.target_success == 7 and loop is True
    assert seed.max_page == 4 and seed.job_key == "test-seed"
    assert detail.solver_enabled and seed.solver_enabled
    assert detail.manual_challenge_reporting and seed.manual_challenge_reporting
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_same_node_pause_and_heartbeat_paths(monkeypatch, tmp_path, prefix):
    configure(
        monkeypatch,
        prefix,
        NODE_ID="PC2",
        WORKER_HEARTBEAT_PATH=str(tmp_path / "heartbeat.json"),
    )
    state = {"running": True, "last_request": {"node_id": "pc2"}}
    assert seed_collector._captcha_solver_targets_current_node(state)
    assert detail_worker._captcha_solver_targets_current_node(state)
    assert WorkerLifecycle("test", lambda _: None).path == tmp_path / "heartbeat.json"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "function,key",
    [
        (live_batch_smoke._analysis_module_b_parallelism, "MAX_PARALLEL"),
        (live_batch_smoke._analysis_module_b_candidate_attempts, "CANDIDATE_ATTEMPTS"),
        (
            live_batch_smoke._analysis_module_b_candidate_retry_seconds,
            "CANDIDATE_RETRY_SECONDS",
        ),
    ],
)
def test_analysis_numeric_fallback_never_hides_alias_conflicts(
    monkeypatch, function, key
):
    configure(monkeypatch, "CROW", **{"ANALYSIS_MODULE_B_" + key: "bad"})
    assert function() in (3, 10.0)
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_" + key, "secret-conflict-value")
    with pytest.raises(EnvironmentAliasConflict) as error:
        function()
    assert "secret-conflict-value" not in str(error.value)


def test_public_cookie_export_does_not_mask_conflict_with_snapshot(
    monkeypatch, tmp_path
):
    configure(
        monkeypatch,
        "CROW",
        COOKIE_SNAPSHOT=str(tmp_path / "cookies.json"),
        COOKIE_SNAPSHOT_PREFER="0",
        CDP_WEBSOCKET_CACHE_PATH=str(tmp_path / "new.json"),
        CDP_RECONNECT_ATTEMPTS="1",
        CDP_RECONNECT_BACKOFF_SECONDS="0",
    )
    monkeypatch.setenv("FAPAI_CDP_WEBSOCKET_CACHE_PATH", str(tmp_path / "old.json"))
    load_snapshot = Mock()
    probe = SimpleNamespace(
        load_cookie_snapshot=load_snapshot,
        export_cdp_cookies=lambda endpoint: transport.export_cdp_cookies(
            endpoint,
            websocket_export=lambda *_: transport._cdp_websocket_cache_path(),
            playwright_export=Mock(),
        ),
    )
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: probe)
    with pytest.raises(EnvironmentAliasConflict):
        live_batch_smoke.export_cookies("http://example.invalid")
    load_snapshot.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_public_cookie_path_keeps_management_root_equivalence(monkeypatch, tmp_path):
    configure(
        monkeypatch,
        "CROW",
        COOKIE_SNAPSHOT="",
        SHARED_DATA_ROOT_HOST="",
        NODE_ID="pc2",
        DATA_ROOT_HOST=str(tmp_path),
    )
    monkeypatch.setenv("FAPAI_DATA_ROOT_HOST", str(tmp_path) + "/")
    assert (
        live_batch_smoke._configured_cookie_snapshot_path()
        == tmp_path / "secrets/nodes/pc2/taobao-cookies.json"
    )


def test_public_seed_source_template_detects_conflicting_aliases(monkeypatch):
    configure(
        monkeypatch, "CROW", SEED_SOURCE_URL_TEMPLATE="https://example.invalid/new"
    )
    monkeypatch.setenv("FAPAI_SEED_SOURCE_URL_TEMPLATE", "https://example.invalid/old")
    with pytest.raises(EnvironmentAliasConflict):
        seed_collector.config_from_env_and_args([])


def test_optional_browser_page_cache_does_not_hide_configuration_conflict(monkeypatch):
    failure = EnvironmentAliasConflict(
        "Conflicting environment aliases: CROW_TEST, FAPAI_TEST"
    )
    monkeypatch.setattr(
        live_batch_smoke, "fetch_open_browser_pages", Mock(side_effect=failure)
    )
    with pytest.raises(EnvironmentAliasConflict):
        live_batch_smoke.load_open_browser_pages("http://example.invalid")


def test_cdp_retry_conflict_is_checked_before_page_compaction(monkeypatch):
    configure(monkeypatch, "CROW", CDP_RECONNECT_ATTEMPTS="1")
    monkeypatch.setenv("FAPAI_CDP_RECONNECT_ATTEMPTS", "2")
    compact = Mock()
    monkeypatch.setattr(live_batch_smoke, "compact_cdp_page_targets_if_needed", compact)
    with pytest.raises(EnvironmentAliasConflict):
        live_batch_smoke.connect_browser_over_cdp(Mock(), "http://example.invalid")
    compact.assert_not_called()


def test_explicit_heartbeat_path_avoids_unrelated_environment_conflict(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CROW_WORKER_HEARTBEAT_PATH", "new")
    monkeypatch.setenv("FAPAI_WORKER_HEARTBEAT_PATH", "old")
    assert (
        WorkerLifecycle("test", lambda _: None, tmp_path / "explicit.json").path
        == tmp_path / "explicit.json"
    )
