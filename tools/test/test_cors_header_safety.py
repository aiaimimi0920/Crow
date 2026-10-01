"""CORS output stays header-safe without changing trusted-origin topology."""

from types import SimpleNamespace

import pytest

from src import server_request_guard as guard

pytestmark = pytest.mark.security


def apply(origin):
    headers = []
    handler = SimpleNamespace(
        headers={"Origin": origin},
        send_header=lambda name, value: headers.append((name, value)),
    )
    guard._apply_cors_headers(handler)
    return headers


@pytest.fixture(autouse=True)
def isolated_origins(monkeypatch):
    monkeypatch.delenv("FAPAI_CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("CROW_CORS_ALLOWED_ORIGINS", raising=False)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8765",
        "http://127.0.0.1:8765",
        "http://[::1]:8765",
        "http://192.0.2.10:8001",
        "https://crow.example.invalid",
        "http://crow-api:8001",
        *guard.CORS_DEFAULT_ORIGINS,
    ],
)
def test_configured_topology_and_trailing_slash_compatibility(monkeypatch, origin):
    monkeypatch.setenv("CROW_CORS_ALLOWED_ORIGINS", f" {origin}/ ")
    for supplied in (origin, origin + "/", " " + origin + " "):
        assert guard._cors_origin_permitted(supplied)
        assert apply(supplied) == [
            ("Access-Control-Allow-Origin", origin),
            ("Vary", "Origin"),
        ]


@pytest.mark.parametrize(
    "byte", ["\r", "\n", "\t", "\x00", "\x1f", "\x7f", "\x85", "\u2028"]
)
@pytest.mark.parametrize("position", ["prefix", "suffix", "middle"])
def test_control_characters_are_never_reflected_even_if_configured(
    monkeypatch, byte, position
):
    origin = "http://localhost:8765"
    malformed = {
        "prefix": byte + origin,
        "suffix": origin + byte,
        "middle": origin + byte + "X-Injected: yes",
    }[position]
    monkeypatch.setenv("CROW_CORS_ALLOWED_ORIGINS", origin)
    assert not guard._cors_origin_permitted(malformed)
    assert apply(malformed) == []
    # Environment values containing NUL cannot be represented by the OS.
    if byte != "\x00":
        monkeypatch.setenv("CROW_CORS_ALLOWED_ORIGINS", malformed)
        assert malformed not in guard._cors_allowed_origins()
        assert apply(malformed) == []


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        "null",
        "NULL",
        "https://evil.example",
        "http://localhost:8766",
        "http://localhost:8765.evil.example",
    ],
)
def test_missing_opaque_and_near_match_origins_are_denied(monkeypatch, origin):
    monkeypatch.setenv("CROW_CORS_ALLOWED_ORIGINS", "http://localhost:8765,null")
    assert not guard._cors_origin_permitted(origin)
    assert apply(origin) == []
