"""Short CDP requests own their session, never the returned buffered response."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import SimpleNamespace

import pytest
import requests

from tools import live_batch_smoke, live_smoke_auth


@pytest.mark.parametrize("module", [live_smoke_auth, live_batch_smoke])
@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize("failure", [None, "timeout", "invalid_url"])
def test_short_cdp_request_closes_owned_session_on_every_exit(
    monkeypatch, module, method, failure
):
    events = []
    response = SimpleNamespace(content=b'{"ok":true}', status_code=200)
    error = (
        requests.Timeout("private request context")
        if failure == "timeout"
        else ValueError("private URL")
    )

    class Session:
        trust_env = True

        def __init__(self):
            self.headers = {}

        def request(self, url, *, timeout):
            assert self.trust_env is False
            assert self.headers == {"Connection": "close"}
            assert url == "http://cdp.test/json/version"
            assert timeout == 1.25
            events.append(method)
            if failure:
                raise error
            return response

        get = put = request

        def close(self):
            events.append("close")

    monkeypatch.setattr(module.requests, "Session", Session)
    fetch = getattr(module, "_cdp_http_" + method)
    if failure:
        with pytest.raises(type(error)) as raised:
            fetch("http://cdp.test/", "/json/version", timeout_seconds=1.25)
        assert raised.value is error
    else:
        assert (
            fetch("http://cdp.test/", "/json/version", timeout_seconds=1.25) is response
        )
        assert response.content == b'{"ok":true}'
    assert events == [method, "close"]


@pytest.mark.parametrize("request_fails", [False, True])
def test_close_failure_never_replaces_request_result_or_original_error(
    monkeypatch, caplog, request_fails
):
    response = object()
    primary = requests.Timeout("token=SECRET")
    calls = []

    class Session:
        def __init__(self):
            self.headers = {}

        def get(self, *args, **kwargs):
            calls.append("get")
            if request_fails:
                raise primary
            return response

        def close(self):
            calls.append("close")
            raise RuntimeError("Authorization: SECRET")

    monkeypatch.setattr(live_smoke_auth.requests, "Session", Session)
    with caplog.at_level("DEBUG", logger="tools.cdp_http_session"):
        if request_fails:
            with pytest.raises(requests.Timeout) as raised:
                live_smoke_auth._cdp_http_get(
                    "http://cdp.test", "/json/version", timeout_seconds=1
                )
            assert raised.value is primary
        else:
            assert (
                live_smoke_auth._cdp_http_get(
                    "http://cdp.test", "/json/version", timeout_seconds=1
                )
                is response
            )
    assert calls == ["get", "close"]
    assert "RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text and "Authorization" not in caplog.text


@pytest.mark.parametrize("method", ["get", "put"])
def test_buffered_reply_remains_readable_after_real_keepalive_socket_is_closed(
    monkeypatch, method
):
    finished = Event()
    body = '{"message":"固定回归"}'.encode()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_PUT = do_GET

        def finish(self):
            try:
                super().finish()
            finally:
                finished.set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        response = getattr(live_batch_smoke, "_cdp_http_" + method)(
            f"http://127.0.0.1:{server.server_port}",
            "/json/version",
            timeout_seconds=2,
        )
        assert finished.wait(2), "The owned keepalive socket was left open"
        assert response.status_code == 200
        assert response.content == body
        assert response.json() == {"message": "固定回归"}
        response.raise_for_status()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not thread.is_alive()
