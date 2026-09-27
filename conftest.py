from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_AVM_HTTP_CONTRACT = "test_avm_http_contract.py"
_HYBRID_SEED_TEST = "test_run_hybrid_seed_collection.py"
_STATEFUL_TERMS = (
    "captcha",
    "collection",
    "maintenance",
    "manual_review",
    "recovery",
    "solver",
)
_SLOW_TERMS = (
    "async",
    "captcha",
    "job",
    "poll",
    "recovery",
    "solver",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--allow-live-network",
        action="store_true",
        default=False,
        help="allow tests marked live_network to use non-loopback sockets",
    )


@pytest.fixture(autouse=True)
def _isolate_pc2_fallback_state(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not Path(str(request.node.path)).name.startswith("test_pc2_"):
        return
    from tools import pc2_solver_state_store

    tmp_path: Path = request.getfixturevalue("tmp_path")
    monkeypatch.setattr(
        pc2_solver_state_store, "FALLBACK_STATE_PATH", tmp_path / "pc2-state.json"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--allow-live-network"):
        return
    skip_live = pytest.mark.skip(
        reason="live network tests require --allow-live-network"
    )
    for item in items:
        if item.get_closest_marker("live_network") is not None:
            item.add_marker(skip_live)


def _network_host_is_local(host: Any) -> bool:
    if host is None:
        return True
    normalized = (
        str(host.decode() if isinstance(host, bytes) else host).strip().strip("[]")
    )
    if not normalized or normalized.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return address.is_loopback


def _socket_address_host(sock: socket.socket, address: Any) -> Any:
    if sock.family == getattr(socket, "AF_UNIX", None):
        return None
    return address[0] if isinstance(address, tuple) and address else address


def _reject_external_socket_address(
    sock: socket.socket,
    address: Any,
    *,
    operation: str,
) -> None:
    host = _socket_address_host(sock, address)
    if not _network_host_is_local(host):
        raise OSError(f"external network disabled during tests ({operation}): {host}")


@pytest.fixture(autouse=True)
def _deny_external_network(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Make repository tests offline unless the operator explicitly opts in."""

    live_network_test = request.node.get_closest_marker("live_network") is not None
    if request.config.getoption("--allow-live-network") and live_network_test:
        yield
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_sendto = socket.socket.sendto
    original_sendmsg = getattr(socket.socket, "sendmsg", None)

    def checked_connect(sock: socket.socket, address: Any) -> Any:
        _reject_external_socket_address(sock, address, operation="connect")
        return original_connect(sock, address)

    def checked_connect_ex(sock: socket.socket, address: Any) -> int:
        _reject_external_socket_address(sock, address, operation="connect_ex")
        return original_connect_ex(sock, address)

    def checked_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) and address else address
        if not _network_host_is_local(host):
            raise OSError(
                f"external network disabled during tests (create_connection): {host}"
            )
        return original_create_connection(address, *args, **kwargs)

    def checked_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _network_host_is_local(host):
            raise OSError(f"external DNS disabled during tests: {host}")
        results = original_getaddrinfo(host, *args, **kwargs)
        if str(host or "").lower() == "localhost":
            for result in results:
                address = result[4]
                resolved_host = (
                    address[0] if isinstance(address, tuple) and address else address
                )
                if not _network_host_is_local(resolved_host):
                    raise OSError(
                        f"localhost resolved outside loopback during tests: {resolved_host}"
                    )
        return results

    def checked_sendto(sock: socket.socket, data: Any, *args: Any) -> Any:
        if not args:
            raise TypeError("sendto requires a destination address")
        _reject_external_socket_address(sock, args[-1], operation="sendto")
        return original_sendto(sock, data, *args)

    def checked_sendmsg(
        sock: socket.socket,
        buffers: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        address = kwargs.get("address")
        if address is None and len(args) >= 3:
            address = args[-1]
        if address is not None:
            _reject_external_socket_address(sock, address, operation="sendmsg")
        assert original_sendmsg is not None
        return original_sendmsg(sock, buffers, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", checked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", checked_connect_ex)
    monkeypatch.setattr(socket, "create_connection", checked_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", checked_getaddrinfo)
    monkeypatch.setattr(socket.socket, "sendto", checked_sendto)
    if original_sendmsg is not None:
        monkeypatch.setattr(socket.socket, "sendmsg", checked_sendmsg)
    yield


def pytest_itemcollected(item: pytest.Item) -> None:
    from scripts.quality_suites import UNIT_FILES

    path = Path(str(item.path))
    if path.name in UNIT_FILES:
        item.add_marker(pytest.mark.unit)
        item.add_marker(pytest.mark.quick)
    if "desktop" in path.name or "collector" in path.name and "ui" in path.name:
        item.add_marker(pytest.mark.desktop)
    if path.name != _AVM_HTTP_CONTRACT:
        return

    item.add_marker(pytest.mark.integration)
    name = item.name.lower()
    if any(term in name for term in _STATEFUL_TERMS):
        item.add_marker(pytest.mark.stateful)
    if any(term in name for term in _SLOW_TERMS):
        item.add_marker(pytest.mark.slow)


@pytest.fixture(autouse=True)
def _deny_unmocked_hybrid_seed_http(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep hybrid seed unit tests offline instead of probing the local API."""

    if Path(str(request.node.path)).name != _HYBRID_SEED_TEST:
        yield
        return

    import requests

    def blocked_get(*_args: Any, **_kwargs: Any) -> None:
        raise requests.ConnectionError("unmocked HTTP is disabled in hybrid seed tests")

    monkeypatch.setattr(requests.Session, "get", blocked_get)
    yield


@pytest.fixture(autouse=True)
def _use_fast_local_server_poll(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate HTTP state and avoid the BaseServer 500 ms shutdown tax."""

    module_name = Path(str(request.node.path)).name
    collection_status = (
        module_name == "test_server_collection_api_status.py"
        or module_name.startswith("server_collection_api_status_test_part_")
    )
    if module_name != _AVM_HTTP_CONTRACT and not collection_status:
        yield
        return

    tmp_path: Path = request.getfixturevalue("tmp_path")
    from src import server as server_module
    from src.runtime_state import RuntimeState

    ReusableTCPServer = server_module.ReusableTCPServer
    original_serve_forever = ReusableTCPServer.serve_forever

    def serve_forever(server: Any, poll_interval: float = 0.01) -> None:
        original_serve_forever(server, poll_interval=poll_interval)

    monkeypatch.setattr(ReusableTCPServer, "serve_forever", serve_forever)
    runtime_root = tmp_path / "server-runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    if collection_status:
        monkeypatch.chdir(runtime_root)
        monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    neutral_runtime = RuntimeState()
    monkeypatch.setattr(server_module, "RUNTIME", neutral_runtime)
    monkeypatch.setattr(server_module, "DATA_DIR", str(runtime_root))
    try:
        yield
    finally:
        snapshot_thread = neutral_runtime.cookie_snapshot.active_thread()
        if snapshot_thread is not None:
            snapshot_thread.join(timeout=1.0)
            if snapshot_thread.is_alive():
                raise AssertionError(
                    f"AVM HTTP contract leaked background thread: {snapshot_thread.name}"
                )
