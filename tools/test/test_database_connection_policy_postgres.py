"""Connection recovery proof, only against the dedicated local quality database."""

import os
import socket

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src.storage.repository_context import DatabaseSettings
from src.storage.repository_core import RepositoryCoreMixin

pytestmark = pytest.mark.integration


@pytest.fixture
def repository():
    value = os.getenv("CROW_TEST_POSTGRES_URL")
    if not value:
        pytest.skip(
            "CROW_TEST_POSTGRES_URL must name a dedicated crow_quality database"
        )
    url = make_url(value)
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "crow_quality":
        pytest.fail("Connection tests require a loopback crow_quality database")
    repo = RepositoryCoreMixin(DatabaseSettings(url=value, enabled=True))
    yield repo
    repo.engine.dispose()


def test_pool_recovers_after_its_own_idle_backend_is_terminated(repository):
    with repository.engine.connect() as connection:
        pid = connection.scalar(text("SELECT pg_backend_pid()"))
    control = create_engine(repository.settings.url)
    try:
        with control.connect() as connection:
            assert connection.scalar(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
            )
        with repository.engine.connect() as connection:
            assert connection.scalar(text("SELECT pg_backend_pid()")) != pid
            assert (
                connection.scalar(text("SELECT current_database()")) == "crow_quality"
            )
    finally:
        control.dispose()


@pytest.mark.skipif(
    not hasattr(socket, "TCP_USER_TIMEOUT"), reason="Linux TCP liveness options"
)
def test_libpq_applies_kernel_dead_peer_detection(repository):
    with repository.engine.connect() as connection:
        raw = connection.connection.driver_connection
        with socket.fromfd(
            raw.pgconn.socket, socket.AF_INET, socket.SOCK_STREAM
        ) as sock:
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE) == 30
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL) == 10
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT) == 3
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) == 60000
