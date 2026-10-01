"""Versioned request bindings; legacy verification only enables exact retries.

This is not an authentication token. New bindings use a salted, expensive KDF
because API keys supplied to compatible local providers can have low entropy.
Old SHA-256 rows can only be upgraded when the original payload is retried.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

ITERATIONS = 600_000
PREFIX = "pbkdf2-sha256-v1$600000$"
_VERSIONED = re.compile(re.escape(PREFIX) + r"([0-9a-f]{32})\$([0-9a-f]{64})")
_LEGACY = re.compile(r"[0-9a-f]{64}")
_DOMAIN = b"Crow.SettingsFingerprint.v1\x00"


def _subject(encoded: str, key: str | None) -> bytes:
    # The HTTP route also caps its whole body at 16 KiB and validates the closed
    # settings schema. Keep direct callers bounded before encoding or hashing.
    if type(encoded) is not str or len(encoded) > 16_384:
        raise ValueError("Invalid fingerprint settings input")
    if key is not None and (type(key) is not str or len(key) > 2048):
        raise ValueError("Invalid fingerprint key input")
    return (encoded + "\n" + (key or "")).encode("utf-8")


def _derive(subject: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", _DOMAIN + subject, salt, ITERATIONS, dklen=32)


def create_fingerprint(encoded: str, key: str | None) -> str:
    subject = _subject(encoded, key)
    salt = secrets.token_bytes(16)
    return PREFIX + salt.hex() + "$" + _derive(subject, salt).hex()


def verify_fingerprint(
    stored: object, encoded: str, key: str | None
) -> tuple[bool, bool]:
    """Return (matches, needs_upgrade); never accept unknown format/cost values.

    The SHA-256 branch is a compatibility verifier, never a new-record writer.
    Erased handoff keys cannot reconstruct old bindings without the retry's
    original payload. Keeping this branch leaves historical risk visible.
    """
    if type(stored) is not str or len(stored) > 128:
        raise ValueError("Invalid settings fingerprint format")
    subject = _subject(encoded, key)
    versioned = _VERSIONED.fullmatch(stored)
    if versioned:
        salt = bytes.fromhex(versioned[1])
        expected = bytes.fromhex(versioned[2])
        return hmac.compare_digest(_derive(subject, salt), expected), False
    if _LEGACY.fullmatch(stored):
        actual = hashlib.sha256(subject).hexdigest()
        return hmac.compare_digest(actual, stored), True
    raise ValueError("Invalid settings fingerprint format")
