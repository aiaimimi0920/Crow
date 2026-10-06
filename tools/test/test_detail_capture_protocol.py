"""Preserve challenge/config/transport classification across the capture boundary."""

import json

import pytest

from src.project_environment import EnvironmentAliasConflict
from tools import detail_browser_capture as boundary
from tools.detail_browser_capture_child import capture_reply
from tools.live_smoke_context import CdpEndpointUnavailableError, DetailChallengeError


def test_public_capture_uses_the_hard_deadline_boundary(monkeypatch):
    from tools import live_batch_smoke as smoke

    expected = ("中文详情", "https://fixture/item", 12, "browser_navigation")
    calls = []
    monkeypatch.setattr(
        boundary,
        "capture_detail_with_deadline",
        lambda seed, **kw: calls.append((seed, kw)) or expected,
    )
    seed = {"url": "https://fixture/item"}
    assert (
        smoke.fetch_detail_with_browser(seed, cdp_endpoint="http://fixture") == expected
    )
    assert calls == [(seed, {"cdp_endpoint": "http://fixture"})]


@pytest.mark.parametrize(
    "error",
    [
        DetailChallengeError(
            "browser detail request", "https://fixture/punish?private=secret"
        ),
        CdpEndpointUnavailableError("http://fixture", "connect", TimeoutError()),
        EnvironmentAliasConflict(
            "Conflicting environment aliases: CROW_TEST, FAPAI_TEST"
        ),
    ],
)
def test_classified_error_survives_private_reply(error):
    def capture(*args, **kwargs):
        raise error

    reply = capture_reply(capture, {"seed": {}, "cdp_endpoint": "http://fixture"})
    with pytest.raises(type(error)) as raised:
        boundary.decode_capture_reply(
            json.dumps(reply).encode("utf-8"), cdp_endpoint="http://fixture"
        )
    for name in ("operation", "challenge_url", "cdp_endpoint"):
        if hasattr(error, name):
            assert getattr(raised.value, name) == getattr(error, name)


def test_timeout_is_transport_failure_not_a_human_challenge(monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutError("blocked content or cleanup")

    monkeypatch.setattr(boundary, "run_capture_process", timeout)
    with pytest.raises(CdpEndpointUnavailableError) as raised:
        boundary.capture_detail_with_deadline(
            {"url": "https://fixture"}, cdp_endpoint="http://fixture"
        )
    assert raised.value.operation == "detail_browser_capture_deadline"
    assert isinstance(raised.value.cause, TimeoutError)


def test_unknown_exception_does_not_serialize_secrets():
    def capture(*args, **kwargs):
        raise RuntimeError("token=DO_NOT_SERIALIZE")

    reply = capture_reply(capture, {"seed": {}, "cdp_endpoint": "http://fixture"})
    assert reply == {
        "kind": "error",
        "diagnostic": {"type": "RuntimeError", "message": "runtime_error"},
    }


def test_real_child_protocol_uses_utf8_for_both_pipe_directions():
    import sys

    script = """
import sys,types
from tools.detail_browser_capture_child import main
fake=types.ModuleType('tools.live_batch_smoke')
fake._fetch_detail_with_browser_attached=lambda seed,**kwargs:(seed['html'],'https://fixture',12,'browser_navigation')
sys.modules['tools.live_batch_smoke']=fake
main()
"""
    request = json.dumps(
        {"seed": {"html": "中文详情"}, "cdp_endpoint": "http://fixture"},
        ensure_ascii=False,
    ).encode("utf-8")
    output = boundary.run_capture_process(
        [sys.executable, "-B", "-c", script], request, timeout_seconds=5
    )
    assert (
        boundary.decode_capture_reply(output, cdp_endpoint="http://fixture")[0]
        == "中文详情"
    )


def test_success_preserves_unicode_and_capture_metadata():
    result = ("中文详情", "https://fixture/item", 12, "browser_navigation")
    reply = capture_reply(
        lambda *args, **kwargs: result, {"seed": {}, "cdp_endpoint": "http://fixture"}
    )
    assert (
        boundary.decode_capture_reply(
            json.dumps(reply, ensure_ascii=False).encode("utf-8"),
            cdp_endpoint="http://fixture",
        )
        == result
    )


@pytest.mark.parametrize(
    "result", [[], ["html", "url", True, "method"], [None, "url", 0, "method"]]
)
def test_invalid_success_reply_fails_closed(result):
    with pytest.raises(RuntimeError, match="Invalid detail capture result"):
        boundary.decode_capture_reply(
            json.dumps({"kind": "ok", "result": result}), cdp_endpoint="http://fixture"
        )
