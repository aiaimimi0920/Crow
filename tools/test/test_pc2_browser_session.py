"""Session checkpoint safety uses fake Docker only."""

import json
import subprocess

import pytest

from tools.pc2_browser_session import BrowserSession


def test_capture_requires_persistent_private_storage():
    calls = []
    session = BrowserSession(runner=lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="Persistent"):
        session.capture({"Id": "a" * 64, "Mounts": []})
    assert not calls


def test_capture_never_prints_or_returns_cookie_values():
    def runner(args, **kwargs):
        code = args[-1]
        compile(code, "checkpoint", "exec")
        import ast

        parsed = ast.parse(code)
        path = next(
            node.value.args[0].value
            for node in parsed.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "path" for t in node.targets)
        )
        return json.dumps({"path": path, "sha256": "a" * 64})

    receipt = BrowserSession(runner=runner).capture(
        {"Id": "a" * 64, "Mounts": [{"Destination": "/app/.codex-temp", "RW": True}]}
    )
    assert set(receipt) == {"path", "sha256"}


def test_restore_retries_startup_failures_and_requires_verified_result():
    calls = []

    def runner(args, **kwargs):
        compile(args[-1], "restore", "exec")
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, args)
        return '{"verified":true}'

    session = BrowserSession(runner=runner, sleep=lambda _: None)
    session.restore("a" * 64, {"path": "/private/session.json", "sha256": "a" * 64})
    assert len(calls) == 2


def test_restore_timeout_is_reported_without_discarding_checkpoint():
    calls = []
    session = BrowserSession(
        runner=lambda args, **kwargs: calls.append(args) or '{"verified":false}',
        sleep=lambda _: None,
    )
    with pytest.raises(RuntimeError, match="checkpoint retained"):
        session.restore("a" * 64, {"path": "/private/session.json", "sha256": "a" * 64})
    assert len(calls) == 30
