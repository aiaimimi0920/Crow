from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import playwright
import pytest

from src import captcha_solver
from tools.test.captcha_solver_test_context import (
    _inject_solver_test_waits as _inject_solver_test_waits,
)


@pytest.mark.parametrize(
    "visible,login,expected",
    [
        (True, False, True),
        (False, False, False),
        (True, True, False),
    ],
)
def test_challenge_dom_distinguishes_retry_widget_from_login(visible, login, expected):
    solver = captcha_solver.CaptchaSolver(port=9223)
    captured = {}
    solver._send_cdp = lambda _method, params: captured.update(params) or {}
    solver._page_challenge_summary()
    driver = Path(playwright.__file__).parent / "driver"
    node = shutil.which("node") or str(
        driver / ("node.exe" if (driver / "node.exe").is_file() else "node")
    )
    harness = """
const vm = require('node:vm');
const options = JSON.parse(process.argv[2]);
const document = {
  body: {className: '', innerText: 'Verification failed. Please refresh page and try again.'},
  title: 'Captcha', readyState: 'complete',
  location: {href: options.login ? 'https://login.taobao.com/' : 'https://sf.taobao.com/list/1.htm/_____tmd_____/punish'},
  querySelector: selector => selector.includes('.errloading') ? {offsetParent: options.visible ? {} : null} : null,
  querySelectorAll: () => [], getElementsByTagName: () => [],
};
console.log(JSON.stringify(vm.runInNewContext(process.argv[1], {document})));
"""
    result = subprocess.run(
        [
            node,
            "-e",
            harness,
            captured["expression"],
            json.dumps({"visible": visible, "login": login}),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=15,
    )
    summary = json.loads(result.stdout)

    assert summary["explicitFailure"] is True
    assert summary["loginRequired"] is login
    assert bool(summary.get("retryableFailure")) is expected


@pytest.mark.parametrize(
    "retryable,reason",
    [
        (True, "challenge_retry_exhausted"),
        (False, "manual_required"),
    ],
)
def test_exhausted_retry_widget_returns_to_bounded_solver_policy(
    monkeypatch, retryable, reason
):
    solver = captcha_solver.CaptchaSolver(
        port=9223, target_url="https://sf.taobao.com/list/1.htm"
    )
    calls = {"drag": 0, "retry": 0}
    solver.connect_tab = lambda: True
    solver._bring_to_front = lambda: True
    solver._find_slider = lambda: {
        "x": 100,
        "y": 100,
        "width": 40,
        "height": 40,
        "selector": "#nc_1_n1z",
        "context": "main",
    }
    solver._get_track_width = lambda: 300
    solver._do_drag = lambda _x, _y, distance: (
        calls.__setitem__("drag", calls["drag"] + 1) or distance
    )
    solver._wait_for_verification_success = lambda: False
    solver._reset_failed_nc_challenge = lambda: (
        calls.__setitem__("retry", calls["retry"] + 1) or True
    )
    solver._page_challenge_summary = lambda: {
        "hardBlock": True,
        "hasSlider": True,
        "explicitFailure": True,
        "retryableFailure": retryable,
        "loginRequired": False,
    }
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert solver.solve(max_attempts=1, nc_retry_replay_limit=2) is False
    assert calls == {"drag": 3, "retry": 2}
    assert solver.last_failure_reason == reason
