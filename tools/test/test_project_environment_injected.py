"""Injected configuration sources must never consult global process settings."""

from types import SimpleNamespace

import pytest

from src.auth_completion_receipts import AuthCompletionReceipts
from src.auth_cookie_paths import AuthCookiePaths
from src.project_environment import EnvironmentAliasConflict
from src.server_auth_cookie import AuthCookieSnapshot


def settings_for(prefix, **values):
    return {
        spelling + "_" + key: value
        for spelling in (["CROW", "FAPAI"] if prefix == "BOTH" else [prefix])
        for key, value in values.items()
    }


def cookie_paths(tmp_path, values):
    return AuthCookiePaths(
        env=values.get,
        repo_root=lambda: tmp_path,
        data_dir=lambda: str(tmp_path / "datas"),
        normalize_node=lambda value: str(value or ""),
        roots=lambda: [tmp_path],
    )


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_cookie_and_receipt_aliases_use_only_the_injected_scope(
    tmp_path, monkeypatch, prefix
):
    for key in (
        "NODE_ID",
        "COOKIE_SNAPSHOT",
        "SOLVER_STATE_DIR",
        "AUTH_COOKIE_RETRY_ATTEMPTS",
    ):
        monkeypatch.setenv("CROW_" + key, "global-new-unrelated")
        monkeypatch.setenv("FAPAI_" + key, "global-old-unrelated")
    values = settings_for(
        prefix,
        NODE_ID="injected",
        COOKIE_SNAPSHOT=str(tmp_path / "fixture.json"),
        SOLVER_STATE_DIR=str(tmp_path / "state"),
        AUTH_COOKIE_RETRY_ATTEMPTS="7",
    )
    paths = cookie_paths(tmp_path, values)
    assert paths._resolve_auth_cookie_snapshot_path({}) == str(
        tmp_path / "fixture.json"
    )
    reader = SimpleNamespace(
        env=values.get, data_dir=lambda: str(tmp_path / "fallback")
    )
    assert (
        AuthCompletionReceipts._auth_completion_confirmation_path(reader)
        == tmp_path / "state/auth-completion-confirmations.json"
    )
    assert AuthCookieSnapshot._auth_cookie_snapshot_retry_attempts(reader) == 7
    values.update(settings_for(prefix, AUTH_COOKIE_RETRY_ATTEMPTS=""))
    assert AuthCookieSnapshot._auth_cookie_snapshot_retry_attempts(reader) == 3
    assert not list(tmp_path.iterdir())


def test_empty_injected_reader_does_not_inherit_global_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("CROW_COOKIE_SNAPSHOT", str(tmp_path / "wrong.json"))
    monkeypatch.setenv("CROW_NODE_ID", "wrong-node")
    monkeypatch.setenv("CROW_AUTH_COOKIE_RETRY_BACKOFF_SECONDS", "99")
    paths = cookie_paths(tmp_path, {})
    assert paths._resolve_auth_cookie_snapshot_path({}) == ""
    assert paths._resolve_auth_cookie_snapshot_path({"node_id": "explicit"}) == str(
        tmp_path / "secrets/nodes/explicit/taobao-cookies.json"
    )
    assert (
        AuthCookieSnapshot._auth_cookie_snapshot_retry_backoff_seconds(
            SimpleNamespace(env={}.get)
        )
        == 2
    )


@pytest.mark.parametrize("prefix", ["CROW", "FAPAI", "BOTH"])
def test_cookie_root_and_sample_url_aliases_are_injected(tmp_path, prefix):
    values = settings_for(
        prefix,
        COOKIE_SNAPSHOT_ROOT=str(tmp_path / "cookies"),
        COOKIE_SNAPSHOT_SAMPLE_URLS="https://example.invalid/a;https://example.invalid/b",
    )
    paths = cookie_paths(tmp_path, values)
    assert paths._auth_cookie_snapshot_root_candidates()[0] == tmp_path / "cookies"
    assert paths._auth_cookie_snapshot_sample_urls({}) == [
        "https://example.invalid/a",
        "https://example.invalid/b",
    ]


def test_management_root_aliases_keep_lexical_path_equivalence_injected(tmp_path):
    values = {
        "CROW_DATA_ROOT_HOST": str(tmp_path / "management") + "/",
        "FAPAI_DATA_ROOT_HOST": str(tmp_path / "management"),
    }
    paths = AuthCookiePaths(
        env=values.get,
        repo_root=lambda: tmp_path,
        data_dir=lambda: str(tmp_path / "custom"),
        normalize_node=lambda value: str(value or ""),
        roots=lambda: [],
    )
    assert paths._auth_cookie_snapshot_root_candidates() == [tmp_path / "management"]
    assert not list(tmp_path.iterdir())


def test_injected_conflict_is_not_numeric_fallback(monkeypatch):
    monkeypatch.setenv("CROW_AUTH_COOKIE_RETRY_ATTEMPTS", "3")
    values = {
        "CROW_AUTH_COOKIE_RETRY_ATTEMPTS": "private-one",
        "FAPAI_AUTH_COOKIE_RETRY_ATTEMPTS": "private-two",
    }
    with pytest.raises(EnvironmentAliasConflict) as error:
        AuthCookieSnapshot._auth_cookie_snapshot_retry_attempts(
            SimpleNamespace(env=values.get)
        )
    assert "private-" not in str(error.value)


def test_challenge_receipt_conflict_is_not_treated_as_missing_state(
    tmp_path, monkeypatch
):
    from src.solver_auth_history import SolverAuthHistory

    monkeypatch.setenv("CROW_SOLVER_STATE_DIR", str(tmp_path / "new-private"))
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path / "old-private"))
    reader = SimpleNamespace(data_dir=lambda: str(tmp_path / "fallback"))
    reader.state_path = lambda: SolverAuthHistory._solver_challenge_state_path(reader)
    with pytest.raises(EnvironmentAliasConflict) as error:
        SolverAuthHistory._read_solver_challenge_state(reader)
    assert "private" not in str(error.value)
    assert not list(tmp_path.iterdir())
