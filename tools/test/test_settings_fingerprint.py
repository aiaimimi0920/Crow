"""Offline format, input, and compatibility contracts for request bindings."""

import pytest

from src import collection_settings_fingerprint as fingerprint

pytestmark = pytest.mark.security
ENCODED = '{"fixture":1}'
KEY = "synthetic-key"


def test_fixed_legacy_vector_is_verifiable_but_never_written():
    # Frozen output of the pre-versioned SHA-256 formula.
    legacy = "03053f7f16fe901667c236c4ae1f5b5e308a477e734f53abf745d68f1939a0d1"
    assert fingerprint.verify_fingerprint(legacy, ENCODED, KEY) == (True, True)
    assert fingerprint.verify_fingerprint(legacy, ENCODED, KEY + "changed") == (
        False,
        True,
    )
    assert fingerprint.create_fingerprint(ENCODED, KEY).startswith(fingerprint.PREFIX)


def test_versioned_vector_and_independent_salts(monkeypatch):
    monkeypatch.setattr(
        fingerprint.secrets, "token_bytes", lambda size: bytes(range(size))
    )
    expected = (
        fingerprint.PREFIX
        + bytes(range(16)).hex()
        + "$"
        + "bd8be2430a59056cd2362c4390782feebb13d0acc824ab97fc237e85902b106b"
    )
    assert fingerprint.create_fingerprint(ENCODED, KEY) == expected
    assert fingerprint.verify_fingerprint(expected, ENCODED, KEY) == (True, False)
    assert fingerprint.verify_fingerprint(expected, ENCODED + " ", KEY) == (
        False,
        False,
    )
    assert fingerprint.verify_fingerprint(expected, ENCODED, KEY + "x") == (
        False,
        False,
    )
    monkeypatch.undo()
    assert fingerprint.create_fingerprint(
        ENCODED, KEY
    ) != fingerprint.create_fingerprint(ENCODED, KEY)


@pytest.mark.parametrize("key", [None, ""])
def test_blank_key_keeps_original_retain_current_key_semantics(key):
    stored = fingerprint.create_fingerprint(ENCODED, key)
    assert fingerprint.verify_fingerprint(stored, ENCODED, None) == (True, False)
    assert fingerprint.verify_fingerprint(stored, ENCODED, "") == (True, False)


@pytest.mark.parametrize(
    "stored",
    [
        None,
        1,
        {},
        "",
        "f" * 63,
        "f" * 65,
        "F" * 64,
        "f" * 64 + "\n",
        "pbkdf2-sha256-v2$600000$" + "a" * 32 + "$" + "b" * 64,
        "pbkdf2-sha256-v1$999999999999$" + "a" * 32 + "$" + "b" * 64,
        "pbkdf2-sha256-v1$1$" + "a" * 32 + "$" + "b" * 64,
        fingerprint.PREFIX + "a" * 30 + "$" + "b" * 64,
        fingerprint.PREFIX + "z" * 32 + "$" + "b" * 64,
        fingerprint.PREFIX + "a" * 32 + "$" + "b" * 62,
        fingerprint.PREFIX + "a" * 32 + "$" + "b" * 64 + "\n",
    ],
)
def test_invalid_versions_costs_and_encodings_fail_before_kdf(monkeypatch, stored):
    monkeypatch.setattr(
        fingerprint, "_derive", lambda *_: pytest.fail("unexpected KDF")
    )
    with pytest.raises(ValueError, match="fingerprint format"):
        fingerprint.verify_fingerprint(stored, ENCODED, KEY)


@pytest.mark.parametrize(
    "encoded,key", [("x" * 16385, KEY), (ENCODED, "x" * 2049), ({}, KEY), (ENCODED, {})]
)
def test_direct_inputs_are_bounded_before_kdf(monkeypatch, encoded, key):
    monkeypatch.setattr(
        fingerprint, "_derive", lambda *_: pytest.fail("unexpected KDF")
    )
    with pytest.raises(ValueError, match="fingerprint .* input"):
        fingerprint.create_fingerprint(encoded, key)


def test_comparison_uses_constant_time_primitive(monkeypatch):
    stored = fingerprint.create_fingerprint(ENCODED, KEY)
    compare = fingerprint.hmac.compare_digest
    calls = []
    monkeypatch.setattr(
        fingerprint.hmac,
        "compare_digest",
        lambda a, b: calls.append((type(a), type(b))) or compare(a, b),
    )
    assert fingerprint.verify_fingerprint(stored, ENCODED, KEY)[0]
    assert calls == [(bytes, bytes)]
