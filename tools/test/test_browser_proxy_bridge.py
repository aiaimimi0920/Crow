"""Synthetic loopback sockets only; no credentials or installed browser access."""

import socket
import threading
import time
from contextlib import contextmanager

import pytest

from tools.browser_proxy_bridge import Bridge, Server


@contextmanager
def bridge_server(upstream, *, maximum=4):
    bridge = Bridge(f"http://sample:password@127.0.0.1:{upstream.getsockname()[1]}")
    with Server(("127.0.0.1", 0), bridge, max_connections=maximum) as server:
        server.join_grace = 0.05
        server.idle_timeout = 1
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=2)


@contextmanager
def listener():
    with socket.socket() as upstream:
        upstream.bind(("127.0.0.1", 0))
        upstream.listen(8)
        upstream.settimeout(2)
        yield upstream


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_rewrite_preserves_request_and_uses_only_configured_credentials():
    bridge = Bridge("http://sample:p%3Ass@127.0.0.1:8888")
    head = b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\nProxy-Authorization: Basic untrusted\r\nConnection: close"
    rewritten = bridge.rewrite_head(head)
    assert rewritten.startswith(
        b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443"
    )
    assert rewritten.count(b"Proxy-Authorization:") == 1
    assert b"Proxy-Authorization: Basic c2FtcGxlOnA6c3M=" in rewritten
    assert rewritten.count(b"Connection:") == 1
    assert rewritten.endswith(b"\r\n\r\n")


def test_disconnected_clients_wake_upstream_receivers_and_reclaim_workers():
    baseline = {thread.ident for thread in threading.enumerate()}
    connections = []
    try:
        with listener() as upstream, bridge_server(upstream) as server:
            for _ in range(4):
                client = socket.create_connection(server.server_address, timeout=2)
                client.sendall(
                    b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test\r\n\r\n"
                )
                peer, _ = upstream.accept()
                peer.settimeout(2)
                assert b"CONNECT" in peer.recv(65536)
                connections.append(peer)
                client.close()
            wait_until(lambda: server.slots._value == 4)
            assert not [
                thread
                for thread in threading.enumerate()
                if thread.ident not in baseline and "pump" in thread.name
            ]
    finally:
        for connection in connections:
            connection.close()


def test_half_closed_request_can_receive_response_without_payload_changes():
    payload = b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\n\x00\x01\xfe\xff"
    with listener() as upstream, bridge_server(upstream) as server:
        client = socket.create_connection(server.server_address, timeout=2)
        try:
            client.sendall(
                b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\n\r\n"
            )
            peer, _ = upstream.accept()
            with peer:
                peer.settimeout(2)
                assert b"GET http://example.test/" in peer.recv(65536)
                client.shutdown(socket.SHUT_WR)
                assert peer.recv(1) == b""
                peer.sendall(payload)
            received = b""
            while chunk := client.recv(65536):
                received += chunk
            assert received == payload
        finally:
            client.close()
        wait_until(lambda: server.slots._value == 4)


def test_connection_limit_rejects_excess_without_spawning_more_workers():
    with listener() as upstream, bridge_server(upstream, maximum=1) as server:
        first = socket.create_connection(server.server_address, timeout=2)
        try:
            wait_until(lambda: server.slots._value == 0)
            with socket.create_connection(server.server_address, timeout=2) as excess:
                assert excess.recv(1) == b""
        finally:
            first.close()
        wait_until(lambda: server.slots._value == 1)


def test_invalid_upstream_error_does_not_include_credentials():
    with pytest.raises(ValueError, match="Invalid upstream proxy address") as caught:
        Bridge("http://sample:password@")
    assert "password" not in str(caught.value)
