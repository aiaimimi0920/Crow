"""Settings use the same bounded JSON transport policy as other API writes."""

import json
import threading
from http.client import HTTPConnection
from types import SimpleNamespace

import pytest

from src import server_collection_settings as settings
from src.collection_http_handler import CollectionRequestHandler
from src.collection_http_server import CollectionHTTPServer

pytestmark = pytest.mark.security


@pytest.fixture
def settings_listener(monkeypatch):
    calls = []

    def record(payload):
        calls.append(payload)
        return {"ok": True}

    store = SimpleNamespace(apply=record, poll=record, finish=record)
    monkeypatch.setattr(settings, "_collection_settings_store", lambda: store)
    monkeypatch.setattr(settings._settings_auth, "authorize", lambda *_: None)
    host = SimpleNamespace(
        ROUTES={
            ("POST", path): "_post_collection_settings"
            for path in settings._settings_schema.ROLES
            if path != settings._settings_schema.PREFIX
        },
        _settings_schema=settings._settings_schema,
        _engine_control=settings._settings_auth,
        _server_collection_settings=settings._server_collection_settings,
    )

    class Handler(CollectionRequestHandler):
        application = host

        def send_json(self, data, status=200):
            encoded = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def send_error_json(self, *, status, **error):
            self.send_json(error, status=status)

        def send_invalid_request_body(self, _payload):
            self.send_error_json(status=400, code="INVALID_OBJECT")

        def log_message(self, *_args):
            pass

    with CollectionHTTPServer(("127.0.0.1", 0), Handler) as httpd:
        thread = threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            yield httpd.server_address, calls
        finally:
            httpd.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()


def post(address, action, body, headers):
    connection = HTTPConnection(*address, timeout=3)
    try:
        connection.request(
            "POST", "/api/collection/settings/" + action, body=body, headers=headers
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


@pytest.mark.parametrize("action", ["apply", "poll", "result"])
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Content-Type": "text/plain"}, 415),
        ({}, 415),
        ({"Content-Type": "application/json", "Transfer-Encoding": "chunked"}, 400),
    ],
)
def test_settings_rejects_unsupported_json_transport(
    settings_listener, action, headers, status
):
    address, calls = settings_listener
    actual, _ = post(address, action, b"{}", {"Content-Length": "2", **headers})
    assert actual == status
    assert calls == []


@pytest.mark.parametrize("action", ["apply", "poll", "result"])
def test_settings_accepts_json_with_charset(settings_listener, action):
    address, calls = settings_listener
    status, result = post(
        address, action, b"{}", {"Content-Type": "application/json; charset=utf-8"}
    )
    assert status == 200 and result["ok"]
    assert calls == [{}]


@pytest.mark.parametrize(
    ("body", "status"),
    [(b" " * 16385, 400), (b"{", 400), (b"[]", 400), (b"\xff\xfe{\x00}\x00", 400)],
    ids=["oversized", "invalid-json", "non-object", "non-utf8"],
)
def test_settings_preserves_size_utf8_and_object_limits(
    settings_listener, body, status
):
    address, calls = settings_listener
    actual, _ = post(address, "poll", body, {"Content-Type": "application/json"})
    assert actual == status
    assert calls == []
