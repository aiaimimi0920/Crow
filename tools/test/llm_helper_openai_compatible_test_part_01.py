from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import requests

from src import llm_helper, llm_model_selector, llm_openai_compatible, llm_websocket
from tools.test.llm_helper_openai_compatible_test_context import (
    _FakeResponse,
    _FakeUtf8Response,
)


def test_compatibility_facade_preserves_exported_class_identity(monkeypatch):
    assert llm_helper.ModelSelector is llm_model_selector.ModelSelector
    assert llm_helper.AIService is llm_websocket.AIService
    assert llm_helper.Ws_Param is llm_websocket.Ws_Param
    monkeypatch.setattr(llm_model_selector, "_selector", None)
    monkeypatch.setattr(llm_model_selector, "get_model_pool", lambda: [])
    assert isinstance(llm_helper.get_model_selector(), llm_helper.ModelSelector)


def test_chat_with_glm_uses_openai_compatible_backend_when_env_is_set(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout, "trust_env": self.trust_env})
            return _FakeResponse()

    def fake_session_factory():
        return FakeSession()

    monkeypatch.setattr(requests, "Session", fake_session_factory)

    class BrokenAIService:
        def __init__(self, *args, **kwargs):
            raise AssertionError("legacy MaaS websocket backend should not be used")

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setattr(llm_openai_compatible, "AIService", BrokenAIService)

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"ok\":true}"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://example.test/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0]["headers"]["Content-Type"] == "application/json"
    assert calls[0]["json"]["model"] == "test-model"
    assert calls[0]["json"]["messages"] == [{"role": "user", "content": "return json"}]
    assert calls[0]["json"]["temperature"] == 0
    assert calls[0]["trust_env"] is False


def test_chat_with_glm_forwards_valid_reasoning_effort(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, _url: str, *, json: dict[str, Any], **_kwargs):
            calls.append(json)
            return _FakeResponse()

    monkeypatch.setattr(requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "LOW")

    result = llm_helper.chat_with_glm("return json")

    assert result == '{"ok":true}'
    assert calls[0]["reasoning_effort"] == "low"


def test_openai_compatible_config_rejects_invalid_reasoning_effort(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "fastest")

    with pytest.raises(ValueError, match="OPENAI_REASONING_EFFORT"):
        llm_helper._get_openai_compatible_config()


@pytest.mark.parametrize("model", ["gpt-5.4", "openai/o3", "codex-mini"])
def test_openai_compatible_analysis_rejects_gpt_related_routes(monkeypatch, model):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", model)

    with pytest.raises(ValueError, match="non-GPT"):
        llm_helper._get_openai_compatible_config()


def test_explicit_analysis_model_rejects_gpt_route_before_request(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "deepseek-v4-flash-0731")
    monkeypatch.setattr(
        llm_openai_compatible,
        "_chat_with_openai_compatible",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("rejected GPT route must not reach the gateway")
        ),
    )

    with pytest.raises(ValueError, match="non-GPT"):
        llm_helper.chat_with_glm("test", model="gpt-5.4")


def test_chat_with_glm_applies_explicit_openai_compatible_proxy_without_trusting_env(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.proxies: dict[str, str] = {}

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float):
            calls.append({"url": url, "proxies": dict(self.proxies), "trust_env": self.trust_env})
            return _FakeResponse()

    monkeypatch.setattr(requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("FAPAI_LLM_HTTP_PROXY", "http://llm-http.proxy:3128")
    monkeypatch.setenv("FAPAI_LLM_HTTPS_PROXY", "http://llm-https.proxy:3128")

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"ok\":true}"
    assert calls == [
        {
            "url": "https://example.test/v1/chat/completions",
            "proxies": {
                "http": "http://llm-http.proxy:3128",
                "https": "http://llm-https.proxy:3128",
            },
            "trust_env": False,
        }
    ]


def test_preflight_openai_compatible_backend_uses_same_proxy_controls(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 401
        text = '{"error":"auth required"}'

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.proxies: dict[str, str] = {}

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            calls.append({"url": url, "headers": headers, "timeout": timeout, "proxies": dict(self.proxies), "trust_env": self.trust_env})
            return FakeResponse()

    monkeypatch.setattr(requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("FAPAI_HTTPS_PROXY", "http://fapai-proxy.local:3128")

    result = llm_helper.preflight_openai_compatible_backend(timeout=7.5)

    assert result == {"enabled": True, "url": "https://example.test/v1/models", "status_code": 401}
    assert calls == [
        {
            "url": "https://example.test/v1/models",
            "headers": {"Authorization": "Bearer test-key"},
            "timeout": 7.5,
            "proxies": {"https": "http://fapai-proxy.local:3128"},
            "trust_env": False,
        }
    ]


def test_preflight_local_openai_compatible_backend_bypasses_generic_fapai_proxy(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 200
        text = '{"data":[]}'

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.proxies: dict[str, str] = {}

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            calls.append({"url": url, "proxies": dict(self.proxies), "trust_env": self.trust_env})
            return FakeResponse()

    monkeypatch.setattr(requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "http://host.docker.internal:8317/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("FAPAI_HTTP_PROXY", "http://collector-proxy.local:3128")
    monkeypatch.setenv("FAPAI_HTTPS_PROXY", "http://collector-proxy.local:3128")

    result = llm_helper.preflight_openai_compatible_backend(timeout=7.5)

    assert result == {"enabled": True, "url": "http://host.docker.internal:8317/v1/models", "status_code": 200}
    assert calls == [
        {
            "url": "http://host.docker.internal:8317/v1/models",
            "proxies": {},
            "trust_env": False,
        }
    ]


def test_preflight_openai_compatible_backend_can_probe_chat_completions(monkeypatch):
    calls: list[dict[str, Any]] = []

    class ModelsResponse:
        status_code = 200
        text = '{"data":[]}'

    class BusyChatResponse:
        status_code = 503
        text = '{"error":"busy"}'

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.proxies: dict[str, str] = {}

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            calls.append({"method": "get", "url": url, "headers": headers, "timeout": timeout, "trust_env": self.trust_env})
            return ModelsResponse()

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float):
            calls.append(
                {
                    "method": "post",
                    "url": url,
                    "headers": headers,
                    "json": json,
                    "timeout": timeout,
                    "trust_env": self.trust_env,
                }
            )
            return BusyChatResponse()

    monkeypatch.setattr(requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    result = llm_helper.preflight_openai_compatible_backend(timeout=7.5, check_chat=True)

    assert result == {
        "enabled": True,
        "url": "https://example.test/v1/models",
        "status_code": 200,
        "chat_url": "https://example.test/v1/chat/completions",
        "chat_status_code": 503,
    }
    assert calls[0] == {
        "method": "get",
        "url": "https://example.test/v1/models",
        "headers": {"Authorization": "Bearer test-key"},
        "timeout": 7.5,
        "trust_env": False,
    }
    assert calls[1]["method"] == "post"
    assert calls[1]["url"] == "https://example.test/v1/chat/completions"
    assert calls[1]["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert calls[1]["json"]["model"] == "test-model"
    assert calls[1]["json"]["messages"] == [
        {
            "role": "user",
            "content": '这是法拍房分析服务连通性检查。请仅返回 JSON：{"ok":true}',
        }
    ]
    assert calls[1]["json"]["temperature"] == 0
    assert calls[1]["json"]["max_tokens"] == 32
    assert calls[1]["timeout"] == 7.5
    assert calls[1]["trust_env"] is False


def test_llm_helper_import_allows_openai_env_without_secrets_json(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(llm_helper.__file__, src_dir / "llm_helper.py")
    shutil.copy2(Path(llm_helper.__file__).parent / "project_environment.py", src_dir / "project_environment.py")
    for module_path in Path(llm_helper.__file__).parent.glob("llm_*.py"):
        if module_path.name != "llm_helper.py":
            shutil.copy2(module_path, src_dir / module_path.name)

    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(tmp_path),
            "OPENAI_BASE_URL": "https://example.test/v1",
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "test-model",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src import llm_helper; "
            "from src import llm_config; "
            "assert llm_config._model_pool is None; "
            "assert not hasattr(llm_helper, 'API_KEY'); "
            "assert not hasattr(llm_helper, 'API_SECRET'); "
            "print('import-ok')",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "import-ok" in result.stdout
    assert "secrets.json not found" not in result.stdout


def test_chat_with_glm_decodes_openai_compatible_utf8_even_without_charset(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, *args, **kwargs):
            return _FakeUtf8Response()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"市场评估价\":1,\"是否成交\":true}"


def test_chat_with_glm_retries_transient_openai_compatible_503(monkeypatch):
    calls: list[int] = []

    class RetryableResponse:
        status_code = 503
        content = b'{"error":"busy"}'
        text = '{"error":"busy"}'

        def raise_for_status(self) -> None:
            raise requests.HTTPError("503 Server Error", response=self)

    class SuccessfulResponse(_FakeResponse):
        content = _FakeResponse.text.encode("utf-8")

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return RetryableResponse()
            return SuccessfulResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "2")
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"ok\":true}"
    assert len(calls) == 2


def test_chat_with_glm_retries_transient_openai_compatible_524(monkeypatch):
    calls: list[int] = []

    class RetryableResponse:
        status_code = 524
        content = b'{"error":"timeout"}'
        text = '{"error":"timeout"}'

        def raise_for_status(self) -> None:
            raise requests.HTTPError("524 Server Error", response=self)

    class SuccessfulResponse(_FakeResponse):
        content = _FakeResponse.text.encode("utf-8")

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return RetryableResponse()
            return SuccessfulResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "2")
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(requests, "Session", lambda: FakeSession())

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"ok\":true}"
    assert len(calls) == 2
