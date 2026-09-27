"""Real collection TLS ingress without production storage or browser startup."""

import json
import socket
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPSConnection
from pathlib import Path

import pytest

from src import server
from src.collection_http_server import tls_context, tls_context_from_env
from tools import docker_entrypoint, run_isolated_collection_api
from tools.test.test_collection_control_https import control as control


@pytest.fixture
def ingress(control, monkeypatch, tmp_path):
    _, cert, _, state = control
    token = tmp_path / "worker.token"
    token.write_text("w" * 48, encoding="utf-8")
    monkeypatch.setenv("FAPAI_COLLECTION_WORKER_TOKEN_FILE", str(token))
    calls = []

    context = tls_context(str(cert), str(state / "server.key"))
    with server.ReusableTCPServer(
        ("127.0.0.1", 0), server.DataHandler, tls=context
    ) as httpd:
        httpd.handshake_timeout = 0.2
        thread = threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            yield httpd, ssl.create_default_context(cafile=str(cert)), calls
        finally:
            httpd.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()


def request(ingress, token=None, context=None):
    httpd, trusted, _ = ingress
    connection = HTTPSConnection(
        *httpd.server_address, context=context or trusted, timeout=2
    )
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-FAPAI-Collection-Token"] = token
    try:
        connection.request("POST", "/api/get_next_task", "{}", headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_tls_preserves_collection_authorization(ingress):
    assert request(ingress)[0] == 403
    assert request(ingress, "wrong")[0] == 403
    assert ingress[2] == []
    status, payload = request(ingress, "w" * 48)
    assert status == 200 and payload["task_type"] == "none"


def test_untrusted_tls_never_reaches_handler_and_listener_recovers(ingress):
    with pytest.raises(ssl.SSLCertVerificationError):
        request(ingress, "w" * 48, ssl.create_default_context())
    assert ingress[2] == []
    assert request(ingress, "w" * 48)[0] == 200


def test_plaintext_and_stalled_handshake_cannot_hold_listener(ingress):
    address = ingress[0].server_address
    with socket.create_connection(address, timeout=2) as plain:
        plain.sendall(b"GET /api/status HTTP/1.0\r\n\r\n")
        try:
            reply = plain.recv(100)
        except ConnectionResetError:
            reply = b""
        assert b"HTTP/" not in reply
    with socket.create_connection(address, timeout=2):
        assert request(ingress, "w" * 48)[0] == 200
    assert ingress[2] == []


def test_stalled_handshake_does_not_delay_a_trusted_client(ingress, monkeypatch):
    httpd = ingress[0]
    httpd.handshake_timeout = 5
    started = threading.Event()
    wrap = httpd.tls.wrap_socket

    def observe_wrap(*args, **kwargs):
        started.set()
        return wrap(*args, **kwargs)

    monkeypatch.setattr(httpd.tls, "wrap_socket", observe_wrap)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with socket.create_connection(httpd.server_address, timeout=2):
            assert started.wait(2)
            ready = pool.submit(request, ingress, "w" * 48)
            assert ready.result(timeout=1)[0] == 200


@pytest.mark.parametrize("cert,key", [("cert.pem", None), (None, "key.pem")])
def test_partial_tls_configuration_fails_closed(cert, key):
    env = {}
    if cert:
        env["FAPAI_API_TLS_CERT_FILE"] = cert
    if key:
        env["FAPAI_API_TLS_KEY_FILE"] = key
    with pytest.raises(ValueError, match="both"):
        tls_context_from_env(env)
    with pytest.raises(ValueError, match="both"):
        docker_entrypoint.build_api_command(env)


def test_invalid_material_fails_before_runtime_initialization(tmp_path, monkeypatch):
    from src import collection_application

    monkeypatch.setattr(
        collection_application,
        "create_application",
        lambda **_: pytest.fail("runtime initialized"),
    )
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert.write_text("invalid certificate", encoding="utf-8")
    key.write_text("invalid private key", encoding="utf-8")
    config = run_isolated_collection_api.build_runtime_config(
        tmp_path, port=0, tls_cert_file=str(cert), tls_key_file=str(key)
    )
    with pytest.raises(ssl.SSLError):
        run_isolated_collection_api.run_server(config)


def test_docker_tls_arguments_reach_isolated_config(monkeypatch):
    env = {
        "FAPAI_API_TLS_CERT_FILE": "/run/secrets/api-cert.pem",
        "FAPAI_API_TLS_KEY_FILE": "/run/secrets/api-key.pem",
    }
    command = docker_entrypoint.build_api_command(env)
    captured = []
    monkeypatch.setattr(
        run_isolated_collection_api,
        "run_server",
        lambda config: captured.append(config) or 0,
    )
    assert run_isolated_collection_api.main(command[2:]) == 0
    assert captured[0]["tls_cert_file"] == env["FAPAI_API_TLS_CERT_FILE"]
    assert captured[0]["tls_key_file"] == env["FAPAI_API_TLS_KEY_FILE"]


def test_http_is_preserved_only_when_no_tls_is_configured():
    assert tls_context_from_env({}) is None
    config = run_isolated_collection_api.build_runtime_config(Path("."), port=0)
    assert config["tls_cert_file"] is None and config["tls_key_file"] is None
