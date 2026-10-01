"""Proxy URL boundaries using only synthetic tokens and ephemeral loopback servers."""

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.collection_engine_restart import RestartError
from src.collection_operator_actions import OPERATOR_ACTION_PATHS
from tools import collection_runtime_proxy as proxy

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "value,expected",
    [
        ("http://127.0.0.1:8001", "http://127.0.0.1:8001"),
        ("http://127.0.0.2:8001/", "http://127.0.0.2:8001"),
        ("http://[::1]:8001", "http://[::1]:8001"),
        ("http://[0:0:0:0:0:0:0:1]:8001/", "http://[::1]:8001"),
    ],
)
def test_origin_rebuilt_from_validated_literal_address(monkeypatch, value, expected):
    monkeypatch.setenv("CROW_CONTROL_LOCAL_API_BASE", value)
    assert proxy.runtime_origin() == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://@127.0.0.1:8001",
        "http://:secret@127.0.0.1:8001",
        "http://127.0.0.1:8001@evil.invalid",
        "http://127.0.0.1.evil.invalid:8001",
        "http://127.0.0.1:8001\\@evil.invalid",
        "http://127.0.0.1:\n8001",
        "http://127.0.0.1:8001/\t",
        "http://127.0.0.1:8001/../",
        "http://127.0.0.1:8001/%2f%2fevil.invalid",
        "http://127.0.0.1:8001?redirect=http://evil.invalid",
        "http://[::1%eth0]:8001",
        "http://[::ffff:192.0.2.1]:8001",
        "http://127.1:8001",
        "http://2130706433:8001",
        "http://localhost:8001",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "https://127.0.0.1:8001",
        "file:///etc/passwd",
    ],
)
def test_ambiguous_origin_never_reaches_transport(monkeypatch, value):
    monkeypatch.setenv("CROW_CONTROL_LOCAL_API_BASE", value)
    monkeypatch.setattr(proxy, "token", lambda _role: "synthetic-only")
    monkeypatch.setattr(
        proxy.urllib.request, "build_opener", lambda *_args: pytest.fail("network")
    )
    with pytest.raises(RestartError) as error:
        proxy.forward_runtime("POST", OPERATOR_ACTION_PATHS["pause"], {})
    assert error.value.status == 503


@pytest.mark.parametrize(
    "path",
    [
        "http://evil.invalid/api/collection/control/pause",
        "//evil.invalid/api/collection/control/pause",
        "/api/collection/control/pause?url=http://evil.invalid",
        "/api/collection/control/pause#fragment",
        "/api/collection/control/../pause",
        "/api/collection/control/%70ause",
        "/api/collection/control/pause/",
        "/api/collection/control/pause\r\nHost: evil.invalid",
    ],
)
def test_request_path_cannot_supply_url_components(monkeypatch, path):
    monkeypatch.setattr(proxy, "runtime_origin", lambda: pytest.fail("origin resolved"))
    with pytest.raises(RestartError) as error:
        proxy.forward_runtime("POST", path, {})
    assert error.value.status == 405


@contextmanager
def _server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_and_environment_proxy_cannot_receive_token(monkeypatch, status):
    received = []
    escaped = []

    class Sink(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            escaped.append((self.path, self.headers.get("X-FAPAI-Control-Token")))
            self.send_response(200)
            self.end_headers()

        do_POST = do_GET

    with _server(Sink) as sink:

        class Runtime(Sink):
            def do_POST(self):
                received.append((self.path, self.headers.get("X-FAPAI-Control-Token")))
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(status)
                self.send_header("Location", sink + "/stolen")
                self.send_header("Content-Length", "0")
                self.end_headers()

        with _server(Runtime) as origin:
            monkeypatch.setenv("CROW_CONTROL_LOCAL_API_BASE", origin)
            monkeypatch.setenv("http_proxy", sink)
            monkeypatch.setenv("HTTP_PROXY", sink)
            monkeypatch.setenv("no_proxy", "")
            monkeypatch.setenv("NO_PROXY", "")
            monkeypatch.setattr(proxy, "token", lambda _role: "synthetic-only")
            with pytest.raises(RestartError) as error:
                proxy.forward_runtime("POST", OPERATOR_ACTION_PATHS["pause"], {})
            assert error.value.status == 502
    assert received == [(OPERATOR_ACTION_PATHS["pause"], "synthetic-only")]
    assert escaped == []
