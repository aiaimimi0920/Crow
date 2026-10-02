"""Breadth-first discovery is explicit and retains legacy region ordering by default."""

from tools import seed_collector as worker


def test_seed_breadth_is_opt_in(monkeypatch):
    monkeypatch.delenv("CROW_SEED_BREADTH_FIRST", raising=False)
    config, _ = worker.config_from_env_and_args([])
    assert config.breadth_first is False


def test_seed_breadth_can_be_enabled_for_parallel_discovery(monkeypatch):
    monkeypatch.setenv("CROW_SEED_BREADTH_FIRST", "1")
    config, _ = worker.config_from_env_and_args(["--parallel-sorts"])
    assert config.breadth_first is True
    assert config.parallel_sorts is True
