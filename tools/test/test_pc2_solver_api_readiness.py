"""A live browser cannot be healthy when its solver reports lack credentials."""

from contextlib import nullcontext
from pathlib import Path

import pytest

from tools import pc2_linux_healthcheck


@pytest.fixture
def ready_browser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("FAPAI_API_BASE_URL", "http://127.0.0.1:8001/api")
    for role, variable in (
        ("worker", "FAPAI_COLLECTION_WORKER_TOKEN_FILE"),
        ("recovery", "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE"),
    ):
        path = tmp_path / f"{role}.token"
        path.write_text(role * 10, encoding="utf-8")
        monkeypatch.setenv(variable, str(path))
    monkeypatch.setattr(
        pc2_linux_healthcheck,
        "_read_json",
        lambda _url: {"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/test"},
    )
    monkeypatch.setattr(
        pc2_linux_healthcheck.socket,
        "create_connection",
        lambda *_a, **_k: nullcontext(),
    )
    monkeypatch.setattr(pc2_linux_healthcheck, "_process_exists", lambda _name: True)
    monkeypatch.setattr(pc2_linux_healthcheck, "_check_rfb_listener", lambda: None)
    monkeypatch.setattr(pc2_linux_healthcheck, "_check_solver_heartbeat", lambda: None)
    return tmp_path


@pytest.mark.parametrize(
    "variable",
    ("FAPAI_COLLECTION_WORKER_TOKEN_FILE", "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE"),
)
def test_browser_rejects_missing_role_credential(
    ready_browser: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.delenv(variable)

    with pytest.raises(RuntimeError, match="solver API credential"):
        pc2_linux_healthcheck.check_browser()


def test_browser_rejects_unreadable_worker_credential(
    ready_browser: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "FAPAI_COLLECTION_WORKER_TOKEN_FILE", str(ready_browser / "missing.token")
    )

    with pytest.raises(RuntimeError, match="solver API credential"):
        pc2_linux_healthcheck.check_browser()


def test_browser_rejects_shared_worker_and_recovery_credential(
    ready_browser: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE", str(ready_browser / "worker.token")
    )

    with pytest.raises(RuntimeError, match="solver API credential"):
        pc2_linux_healthcheck.check_browser()


def test_browser_accepts_distinct_role_credentials(ready_browser: Path) -> None:
    pc2_linux_healthcheck.check_browser()
