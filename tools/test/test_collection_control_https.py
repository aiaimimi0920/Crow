"""Real loopback TLS with synthetic CA/tokens, no live services or credentials."""

import datetime
import ipaddress
import json
import threading
import urllib.error

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from tools.collection_control_https import create_server
from tools.desktop_settings_client import execute
from tools.pc2_engine_controller import MailboxClient
from tools.pc2_settings_controller import SettingsClient
from tools.test.collection_settings_fixtures import config_fixture


@pytest.fixture
def control(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Crow test only")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    ca, private = tmp_path / "ca.pem", tmp_path / "server.key"
    ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    tokens = {}
    for role, letter in [("operator", "o"), ("agent", "a")]:
        tokens[role] = tmp_path / (role + ".token")
        tokens[role].write_text(letter * 48, encoding="utf-8")
        monkeypatch.setenv(
            "FAPAI_ENGINE_" + role.upper() + "_TOKEN_FILE", str(tokens[role])
        )
    server = create_server(("127.0.0.1", 0), tmp_path / "state", ca, private)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    origin = f"https://127.0.0.1:{server.server_port}"
    env = {
        "FAPAI_SETTINGS_API_BASE": origin,
        "FAPAI_SETTINGS_CA_FILE": str(ca),
        "FAPAI_ENGINE_OPERATOR_TOKEN_FILE": str(tokens["operator"]),
    }
    for key in env:
        monkeypatch.delenv(key, raising=False)
    # The service role token must remain configured; bundle selection uses the same fixture.
    monkeypatch.setenv("FAPAI_ENGINE_OPERATOR_TOKEN_FILE", str(tokens["operator"]))
    (tmp_path / "crow-desktop.runtime.json").write_text(
        json.dumps({"version": 1, "environment": env}), encoding="utf-8"
    )
    try:
        yield origin, ca, tokens, tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_private_ca_role_boundary_and_desktop_receipt(control):
    origin, ca, tokens, root = control
    agent = SettingsClient(origin, tokens["agent"], ca_file=ca)
    operator = SettingsClient(origin, tokens["operator"], ca_file=ca)
    config = config_fixture()
    agent.post("poll", {"effective": config, "api_key_configured": True})
    state = execute({"action": "get", "origin": origin}, root)
    assert state["available"] is True and state["effective"] == config
    body = {
        "request_id": "settings-tls-fixture-001",
        "expected_revision": state["revision"],
        "config": config,
        "api_key": None,
    }
    receipt = execute({"action": "apply", "origin": origin, "body": body}, root)
    assert receipt["request"]["status"] == "requested"
    command = agent.post("poll", {"effective": config, "api_key_configured": True})[
        "command"
    ]
    final = {
        "request_id": command["request_id"],
        "claim": command["claim"],
        "result": "applied",
        "effective": config,
        "api_key_configured": True,
    }
    assert agent.post("result", final) == agent.post("result", final)
    assert operator.get()["request"]["status"] == "succeeded"
    with pytest.raises(urllib.error.HTTPError) as error:
        operator.post("poll", {"effective": config, "api_key_configured": True})
    assert error.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as error:
        agent.get()
    assert error.value.code == 403
    with pytest.raises(urllib.error.URLError):
        SettingsClient(origin, tokens["operator"]).get()
    with pytest.raises(ValueError):
        execute({"action": "get", "origin": "https://unconfigured.invalid"}, root)
    assert execute({"action": "config"}, root)["configured"] is True
    assert not list((root / "state").glob("**/*postgres*"))


def test_restart_mailbox_shares_tls_but_never_executes_docker(control):
    origin, ca, tokens, _ = control
    agent = MailboxClient(origin, tokens["agent"], ca_file=ca)
    operator = MailboxClient(origin, tokens["operator"], ca_file=ca)
    assert agent.post("poll", {})["command"] is None
    operator.request("", {"request_id": "restart-tls-fixture-001"})
    command = agent.post("poll", {})["command"]
    agent.post(
        "result",
        {
            "request_id": command["request_id"],
            "claim": command["claim"],
            "result": "workers_ready",
        },
    )
    assert operator.get()["request"]["status"] == "succeeded"
