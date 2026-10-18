import io
import json
import struct

import pytest

from tools import edge_auth_store as store
from tools.edge_auth_contract import MAX_MESSAGE, normalize_cookies
from tools.edge_auth_host import exchange
from tools.pc1_desktop_recovery import RecoveryError

REQUEST = "a" * 32
PROFILE = "b" * 32
URL = "https://sf.taobao.com/list/50025969.htm"
API = "https://fixture.invalid/api/collection/auth/recovery"
COOKIE = {
    "name": "fixture",
    "value": "synthetic",
    "domain": ".taobao.com",
    "path": "/",
    "secure": True,
    "httpOnly": True,
    "sameSite": "no_restriction",
}


@pytest.fixture
def mailbox(tmp_path):
    store.create_task(
        tmp_path,
        request_id=REQUEST,
        url=URL,
        scope="seed",
        api=API,
        challenge_id="challenge",
    )
    claim = store.handle(tmp_path, {"action": "claim", "profile_id": PROFILE})
    return tmp_path, {
        "action": "submit",
        "profile_id": PROFILE,
        "request_id": REQUEST,
        "nonce": claim["nonce"],
        "tab_url": URL,
        "user_agent": "Edge fixture",
        "cookies": [COOKIE],
    }


def test_only_explicit_submit_stores_cookies_and_no_credentials_in_claim(mailbox):
    root, message = mailbox
    claim = store.handle(root, {"action": "claim", "profile_id": PROFILE})
    assert "api" not in claim and "cookies" not in claim
    assert not (root / (REQUEST + ".json")).exists()
    assert store.handle(root, message) == {"submitted": True}
    value = store.read(root / (REQUEST + ".json"))
    assert value["cookies"][0]["httpOnly"] is True
    assert value["cookies"][0]["sameSite"] == "None"
    with pytest.raises(RecoveryError, match="edge_already_submitted"):
        store.handle(root, message)


@pytest.mark.parametrize(
    "key,value,code",
    [
        ("profile_id", "c" * 32, "edge_wrong_profile"),
        ("nonce", "c" * 32, "edge_task_changed"),
        ("request_id", "c" * 32, "edge_task_changed"),
        ("tab_url", URL + "?changed=1", "challenge_page_not_ready"),
        ("tab_url", "https://evil.invalid/list/a", "invalid_target"),
        ("user_agent", "bad\nvalue", "edge_invalid_request"),
    ],
)
def test_wrong_identity_never_publishes(mailbox, key, value, code):
    root, message = mailbox
    with pytest.raises(RecoveryError, match=code):
        store.handle(root, message | {key: value})
    assert not (root / (REQUEST + ".json")).exists()


def test_expired_replaced_and_cross_profile_claim(mailbox, monkeypatch):
    root, message = mailbox
    with pytest.raises(RecoveryError, match="edge_wrong_profile"):
        store.handle(root, {"action": "claim", "profile_id": "c" * 32})
    store.create_task(
        root, request_id="d" * 32, url=URL, scope="seed", api=API, challenge_id="new"
    )
    with pytest.raises(RecoveryError, match="edge_task_changed"):
        store.handle(root, message)
    monkeypatch.setattr(store.time, "time", lambda: 10**12)
    with pytest.raises(RecoveryError, match="edge_task_expired"):
        store.handle(root, {"action": "claim", "profile_id": PROFILE})


@pytest.mark.parametrize(
    "change",
    [
        {"domain": ".evil.invalid"},
        {"domain": ".taobao.com.evil.invalid"},
        {"partitionKey": {"topLevelSite": "https://taobao.com"}},
        {"name": ""},
        {"value": "bad\r\nvalue"},
        {"path": "bad"},
        {"httpOnly": "true"},
        {"sameSite": "unknown"},
        {"expirationDate": float("nan")},
        {"expirationDate": True},
        {"value": "a" * 16385},
    ],
)
def test_cookie_contract_rejects_unsafe_or_unsupported_input(change):
    with pytest.raises(RecoveryError):
        normalize_cookies([COOKIE | change])


@pytest.mark.parametrize("values", [[], [COOKIE, COOKIE], [None], "not-list"])
def test_cookie_collection_bounds(values):
    with pytest.raises(RecoveryError):
        normalize_cookies(values)


def test_capture_requires_same_task_and_actual_http_health(mailbox, monkeypatch):
    from tools import taobao_inplace_auth_handoff as handoff

    root, message = mailbox
    store.handle(root, message)
    args = {
        "request_id": REQUEST,
        "api": API,
        "scope": "seed",
        "url": URL,
        "challenge_id": "challenge",
    }
    monkeypatch.setattr(
        handoff, "_validate_cookie_http", lambda *a, **kw: {"healthy": False}
    )
    with pytest.raises(RecoveryError, match="session_not_reusable"):
        store.capture(root, **args)
    for key, value in [
        ("api", "https://other.invalid"),
        ("scope", "detail"),
        ("challenge_id", "new"),
    ]:
        with pytest.raises(RecoveryError, match="edge_task_changed"):
            store.capture(root, **(args | {key: value}))
    monkeypatch.setattr(
        handoff, "_validate_cookie_http", lambda *a, **kw: {"healthy": True}
    )
    assert json.loads(store.capture(root, **args))[0]["value"] == "synthetic"
    store.create_task(
        root,
        request_id=REQUEST,
        url=URL,
        scope="seed",
        api=API,
        challenge_id="challenge",
    )
    with pytest.raises(RecoveryError, match="edge_task_changed"):
        store.capture(root, **args)


def test_native_framing_and_errors_do_not_leak_exception():
    raw = json.dumps({"action": "claim"}).encode()
    source, sink = io.BytesIO(struct.pack("<I", len(raw)) + raw), io.BytesIO()
    exchange(source, sink, lambda _: {"submitted": True})
    result = sink.getvalue()
    assert struct.unpack("<I", result[:4])[0] == len(result[4:])
    assert json.loads(result[4:]) == {"ok": True, "submitted": True}

    def fail(_):
        raise ValueError("secret material")

    sink = io.BytesIO()
    exchange(io.BytesIO(struct.pack("<I", len(raw)) + raw), sink, fail)
    assert b"secret" not in sink.getvalue()
    for raw in [b"", b"xx", struct.pack("<I", MAX_MESSAGE + 1)]:
        sink = io.BytesIO()
        exchange(io.BytesIO(raw), sink, fail)
        assert sink.getvalue() == b""


def test_extension_id_matches_public_key_and_permissions():
    import base64
    import hashlib
    from pathlib import Path

    from tools.edge_auth_contract import EXTENSION_ID

    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "browser-extension/crow-auth/manifest.json").read_text(encoding="utf-8")
    )
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    assert "".join(chr(97 + int(c, 16)) for c in digest) == EXTENSION_ID
    assert set(manifest["permissions"]) == {"cookies", "storage", "nativeMessaging"}
    assert all(
        "*://" not in host and "*." not in host for host in manifest["host_permissions"]
    )
    assert "background" not in manifest and "content_scripts" not in manifest
