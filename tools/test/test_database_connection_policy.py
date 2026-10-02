"""Network liveness defaults must preserve database identity and explicit policy."""

import pytest

from src.storage.connection_policy import engine_connection_options


@pytest.mark.parametrize(
    "driver", ["postgresql", "postgresql+psycopg", "postgresql+psycopg2"]
)
def test_libpq_connections_detect_lost_peer(driver):
    result = engine_connection_options(f"{driver}://user:secret@host/original_db")
    assert result["pool_pre_ping"] is True
    assert result["connect_args"] == {
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
        "tcp_user_timeout": 60000,
    }


def test_explicit_url_settings_are_not_overwritten():
    result = engine_connection_options(
        "postgresql+psycopg://host/original_db?connect_timeout=22&"
        "keepalives_idle=90&tcp_user_timeout=180000&options=-cstatement_timeout%3D5000"
    )
    assert set(result["connect_args"]) == {
        "keepalives",
        "keepalives_interval",
        "keepalives_count",
    }


def test_non_libpq_driver_does_not_receive_libpq_arguments():
    assert engine_connection_options("postgresql+pg8000://host/db") == {
        "pool_pre_ping": True
    }


@pytest.mark.parametrize(
    "url", ["sqlite://", "sqlite:///old.db", "mysql+pymysql://host/db"]
)
def test_other_backends_are_unchanged(url):
    assert engine_connection_options(url) == {}


def test_repository_engine_uses_policy_without_rewriting_database_url(monkeypatch):
    from src.storage import repository_core
    from src.storage.repository_context import DatabaseSettings

    seen = {}
    sentinel = object()

    def create(url, **options):
        seen.update(url=url, **options)
        return sentinel

    monkeypatch.setattr(repository_core, "create_engine", create)
    url = "postgresql+psycopg://user:secret@host/fapaifang?keepalives_idle=90"
    repository = repository_core.RepositoryCoreMixin(
        DatabaseSettings(url=url, enabled=True)
    )
    assert repository.engine is sentinel
    assert seen["url"] == url
    assert seen["pool_pre_ping"] is True
    assert "keepalives_idle" not in seen["connect_args"]
