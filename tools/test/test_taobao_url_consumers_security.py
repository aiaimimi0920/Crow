"""Source-specific health, pause, and data-fixer policies use URL identity."""

import ast
import glob
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.captcha_solver import CaptchaSolver
from src.collection.adapters.taobao_health import classify_taobao_health
from src.collection.adapters.taobao_solver_target import (
    _is_web_target_domain,
    _split_web_target_url,
)
from tools import seed_collector
from tools.seed_collector_auth import _pause_state_blocks_seed_stage

pytestmark = [pytest.mark.security, pytest.mark.unit]


@pytest.mark.parametrize(
    "url",
    [
        "https://login.taobao.com.attacker.test/",
        "https://login.m.taobao.com.attacker.test/",
        "https://login.taobao.com@attacker.test/",
        "https://attacker.test/?next=https://login.taobao.com/",
        "https://attacker.test/#https://login.m.taobao.com/",
        "https://attacker.test/havanaone/login/login.htm",
        "https://sf.taobao.com/?next=/havanaone/login/login.htm",
        "https://sf.taobao.com/havanaone/login-malicious",
        "https://login.taobao.com:bad/",
        "https://[bad",
    ],
)
def test_health_does_not_infer_login_from_an_untrusted_url_component(url):
    result = classify_taobao_health("", final_url=url, payload_present=False)
    assert result["status"] == "unknown_blocked"


@pytest.mark.parametrize(
    "url",
    [
        "HTTP://LOGIN.TAOBAO.COM/",
        "https://login.m.taobao.com/",
        "https://login.tmall.com/",
        "https://sf.taobao.com/havanaone/login/login.htm",
    ],
)
def test_health_preserves_supported_login_hosts_and_paths(url):
    assert (
        classify_taobao_health("", final_url=url, payload_present=False)["status"]
        == "login_required"
    )


def test_health_preserves_authoritative_summary_login_evidence():
    result = classify_taobao_health(
        "",
        final_url="https://example.test/",
        payload_present=False,
        list_summary={"body_has_login": True},
    )
    assert result["status"] == "login_required"


@pytest.mark.parametrize(
    "pause_blocks",
    [
        _pause_state_blocks_seed_stage,
        seed_collector._pause_state_blocks_seed_stage,
    ],
)
@pytest.mark.parametrize(
    "url,blocks_seed",
    [
        ("https://sf-item.taobao.com/sf_item/123.htm", False),
        ("HTTP://SF-ITEM.TAOBAO.COM/sf_item/123.htm", False),
        ("https://paimai.tmall.com/sf_item/123.htm", False),
        ("https://sf.taobao.com/list/123.htm", True),
        ("https://sf-item.taobao.com.attacker.test/", True),
        ("https://attacker.test/sf_item/123.htm", True),
        ("https://attacker.test/?next=https://sf-item.taobao.com/", True),
        ("https://sf.taobao.com/?next=/sf_item/123.htm", True),
        ("https://sf-item.taobao.com:bad/sf_item/123.htm", True),
        ("https://user:password@sf-item.taobao.com/sf_item/123.htm", True),
    ],
)
def test_seed_pause_bypass_requires_real_detail_identity(
    pause_blocks, url, blocks_seed
):
    state = {"paused": True, "captcha_solver": {"last_request": {"target_url": url}}}
    assert pause_blocks(state) is blocks_seed
    state["scope"] = "seed"
    assert pause_blocks(state) is True


def test_data_fixer_scan_queues_only_real_taobao_sources(tmp_path):
    # Execute the actual scan method with a synthetic data directory and tiny
    # schema, avoiding GUI/AI startup and any configured runtime-data location.
    source = Path(__file__).parents[2] / "src/data_fixer_app_part_01.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "scan_missing_data"
    )
    namespace = {
        "glob": glob,
        "json": json,
        "os": os,
        "logger": logging.getLogger(__name__),
        "DATAS_DIR": str(tmp_path),
        "FIELDS_SCHEMA": [{"key": "area", "label": "Area", "type": "number"}],
        "INFERABLE_FIELDS": set(),
        "_is_web_target_domain": _is_web_target_domain,
        "_split_web_target_url": _split_web_target_url,
    }
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    accepted = [
        "https://sf-item.taobao.com/sf_item/123.htm",
        "HTTP://TAOBAO.COM/",
        "https://sf.taobao.com/list/123.htm",
    ]
    rejected = [
        "https://taobao.com.attacker.test/",
        "https://evil-taobao.com/",
        "https://taobao.com@attacker.test/",
        "https://attacker.test/?next=https://taobao.com/",
        "https://attacker.test/taobao.com/",
        "https://sf.taobao.com:bad/",
        "https://bad..taobao.com/",
        "javascript://taobao.com/",
        "https://tmall.com/",
    ]
    (tmp_path / "fixture.json").write_text(
        json.dumps(
            [
                {"id": index, "原始网站": url}
                for index, url in enumerate(accepted + rejected)
            ]
        ),
        encoding="utf-8",
    )
    app = SimpleNamespace(
        ai_verify_queue=[], log=lambda _message: None, update_status=lambda: None
    )
    namespace["scan_missing_data"](app)
    assert [task["url"] for task in app.task_queue] == accepted


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.test/?next=https://sf.taobao.com/list/123.htm",
        "https://attacker.test/?next=/_____tmd_____/punish",
    ],
)
def test_destination_recovery_does_not_navigate_to_an_embedded_route(url):
    solver = CaptchaSolver()
    solver._send_cdp = lambda *_args, **_kwargs: {"result": {"value": url}}
    assert (
        solver._destination_list_url() == "https://sf.taobao.com/list/50025969__2.htm"
    )


def test_destination_recovery_keeps_generic_http_challenge_route():
    solver = CaptchaSolver()
    solver._send_cdp = lambda *_args, **_kwargs: {
        "result": {"value": "http://localhost:9000/mock/_____tmd_____/punish?x5step=1"}
    }
    assert solver._destination_list_url() == "http://localhost:9000/mock"
