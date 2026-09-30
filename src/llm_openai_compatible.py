from __future__ import annotations

import json
import logging
import os
import re
import time
from urllib.parse import urlparse

import requests

from src.project_environment import getenv as project_getenv
from src.llm_config import get_model_pool
from src.llm_model_selector import (
    AUTH_INVALID_ERROR_CODES,
    LLMBackendUnavailableError,
    get_model_selector,
)
from src.llm_websocket import AIService
from src.llm_analysis_policy import require_non_gpt_analysis_model


logger = logging.getLogger(__name__)


def _strip_json_markdown(result):
    if "```json" in result:
        return result.split("```json")[1].split("```")[0].strip()
    if "```" in result:
        return result.split("```")[1].split("```")[0].strip()
    return result


def _get_openai_compatible_config():
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
    )
    api_key = os.environ.get("OPENAI_API_KEY")
    if not base_url or not api_key:
        return None
    primary_model = (
        os.environ.get("OPENAI_MODEL")
        or os.environ.get("OPENAI_COMPATIBLE_MODEL")
        or "deepseek-v4-flash-0731"
    )
    candidate_text = os.environ.get("OPENAI_MODEL_CANDIDATES") or ""
    models = []
    for candidate in [primary_model, *re.split(r"[;,]", candidate_text)]:
        normalized = str(candidate or "").strip()
        if normalized:
            normalized = require_non_gpt_analysis_model(
                normalized,
                setting="OPENAI_MODEL/OPENAI_MODEL_CANDIDATES",
            )
        if normalized and normalized not in models:
            models.append(normalized)
    config = {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": models[0],
        "models": models,
        "timeout": float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "180")),
        "max_retries": int(os.environ.get("OPENAI_MAX_RETRIES", "3")),
    }
    reasoning_effort = str(os.environ.get("OPENAI_REASONING_EFFORT") or "").strip().lower()
    if reasoning_effort:
        allowed_reasoning_efforts = {"none", "minimal", "low", "medium", "high", "xhigh"}
        if reasoning_effort not in allowed_reasoning_efforts:
            raise ValueError(
                "OPENAI_REASONING_EFFORT must be one of: "
                + ", ".join(sorted(allowed_reasoning_efforts))
            )
        config["reasoning_effort"] = reasoning_effort
    return config


def _first_nonempty_env(*names):
    for name in names:
        value = project_getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _is_local_openai_compatible_url(base_url):
    host = (urlparse(str(base_url)).hostname or "").strip().lower()
    return host in {
        "localhost",
        "127.0.0.1",
        "::1",
        "host.docker.internal",
        "gateway.docker.internal",
        "host.containers.internal",
        "192.168.65.254",
    }


def _get_openai_compatible_proxies(base_url=None):
    fallback_proxy = _first_nonempty_env("OPENAI_PROXY", "CROW_LLM_PROXY")
    explicit_http_proxy = _first_nonempty_env("OPENAI_HTTP_PROXY", "CROW_LLM_HTTP_PROXY")
    explicit_https_proxy = _first_nonempty_env("OPENAI_HTTPS_PROXY", "CROW_LLM_HTTPS_PROXY")
    if base_url and _is_local_openai_compatible_url(base_url) and not (
        fallback_proxy or explicit_http_proxy or explicit_https_proxy
    ):
        return {}

    http_proxy = explicit_http_proxy or _first_nonempty_env("CROW_HTTP_PROXY") or fallback_proxy
    https_proxy = explicit_https_proxy or _first_nonempty_env("CROW_HTTPS_PROXY") or fallback_proxy or http_proxy
    proxies = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


def _chat_with_openai_compatible(content, config):
    from src.llm_request_policy import MAX_OUTPUT_TOKENS, MAX_RETRY_WAIT_SECONDS, retry_delay
    from src.llm_evidence_prompt import request_messages

    url = f"{config['base_url']}/chat/completions"
    session = requests.Session()
    session.trust_env = False
    proxies = _get_openai_compatible_proxies(config["base_url"])
    if proxies:
        session.proxies = proxies
    max_retries = max(int(config.get("max_retries", 3)), 1)
    models = list(config.get("models") or [config["model"]])
    response = None
    forbidden_models = set()
    for attempt in range(1, max_retries + 1):
        wait_seconds = min(2 ** (attempt - 1), 8)
        for model in models:
            if model in forbidden_models:
                continue
            request_payload = {
                "model": model,
                "messages": request_messages(content),
                "temperature": 0,
                "max_tokens": MAX_OUTPUT_TOKENS,
            }
            if config.get("reasoning_effort"):
                request_payload["reasoning_effort"] = config["reasoning_effort"]
            response = session.post(
                url,
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=config["timeout"],
            )
            status_code = getattr(response, "status_code", None)
            if status_code is not None and status_code < 400:
                config["last_successful_model"] = model
                break
            if status_code in (400, 401):
                response.raise_for_status()
            if status_code == 403:
                forbidden_models.add(model)
            if status_code == 429:
                wait_seconds = retry_delay(getattr(response, "headers", {}), attempt)
                # Rate limiting can be account-wide; do not fan out to every model.
                break
            if status_code not in (403, 429, 500, 502, 503, 504, 524):
                response.raise_for_status()
        if response is not None and getattr(response, "status_code", None) is not None and response.status_code < 400:
            break
        if attempt >= max_retries or len(forbidden_models) == len(models):
            break
        if wait_seconds > MAX_RETRY_WAIT_SECONDS:
            response.raise_for_status()
        logger.debug(
            "OpenAI-compatible candidate models unavailable; retry %s/%s after %ss",
            attempt,
            max_retries,
            wait_seconds,
        )
        time.sleep(wait_seconds)
    if response is None:
        raise LLMBackendUnavailableError("LLM backend unavailable: no OpenAI-compatible model candidates")
    response.raise_for_status()
    raw_bytes = getattr(response, "content", None)
    if isinstance(raw_bytes, (bytes, bytearray)):
        raw_payload = raw_bytes.decode("utf-8")
    else:
        raw_payload = str(getattr(response, "text", ""))
    payload = json.loads(raw_payload)
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not choices:
        raise ValueError("OpenAI-compatible response missing choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    result = message.get("content") if isinstance(message, dict) else None
    if not result:
        raise ValueError("OpenAI-compatible response missing message content")
    return result


def preflight_openai_compatible_backend(timeout=15.0, *, check_chat=False):
    config = _get_openai_compatible_config()
    if not config:
        return {"enabled": False}
    from src.llm_qualification_pool import QualifiedModelPool, pool_enabled
    if pool_enabled():
        import sqlite3
        try:
            pool = QualifiedModelPool(config, proxies=_get_openai_compatible_proxies(config["base_url"]))
            models = pool.refresh_in_background()
        except (OSError, sqlite3.Error, ValueError):
            models = []
        return {"enabled": True, "status_code": 200 if models else 503,
                "chat_status_code": 200 if models else 503, "qualified_models": models,
                "model_pool": "ready" if models else "exhausted_or_probing"}
    url = f"{config['base_url']}/models"
    session = requests.Session()
    session.trust_env = False
    proxies = _get_openai_compatible_proxies(config["base_url"])
    if proxies:
        session.proxies = proxies
    try:
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {config['api_key']}"},
            timeout=float(timeout),
        )
    except requests.RequestException as exc:
        return {
            "enabled": True,
            "url": url,
            "status_code": 0,
            "error_type": type(exc).__name__,
        }
    result = {
        "enabled": True,
        "url": url,
        "status_code": getattr(response, "status_code", None),
    }
    if check_chat:
        chat_url = f"{config['base_url']}/chat/completions"
        models = list(config.get("models") or [config["model"]])
        chat_response = None
        chat_model = None
        for model in models:
            try:
                request_payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": '这是法拍房分析服务连通性检查。请仅返回 JSON：{"ok":true}',
                        }
                    ],
                    "temperature": 0,
                    "max_tokens": 32,
                }
                if config.get("reasoning_effort"):
                    request_payload["reasoning_effort"] = config["reasoning_effort"]
                chat_response = session.post(
                    chat_url,
                    headers={
                        "Authorization": f"Bearer {config['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                    timeout=float(timeout),
                )
            except requests.RequestException as exc:
                chat_response = None
                result.setdefault("probe_errors", []).append(
                    {"model_name": model, "error_type": type(exc).__name__}
                )
                continue
            status_code = getattr(chat_response, "status_code", None)
            if status_code is not None and status_code < 400:
                chat_model = model
                break
            if status_code in (400, 401):
                break
        result.update(
            {
                "chat_url": chat_url,
                "chat_status_code": getattr(chat_response, "status_code", None),
            }
        )
        if len(models) > 1:
            result["chat_model_name"] = chat_model
    return result


def preflight_llm_backend(timeout=15.0, *, check_chat=False):
    config = _get_openai_compatible_config()
    if config:
        result = preflight_openai_compatible_backend(timeout=timeout, check_chat=check_chat)
        result.setdefault("backend", "openai_compatible")
        return result
    pool = get_model_pool()
    if not pool:
        return {"enabled": False}

    result = {
        "enabled": True,
        "backend": "glm_websocket_pool",
        "model_pool_size": len(pool),
    }
    if not check_chat:
        return result

    disabled_models = dict(getattr(get_model_selector(), "disabled_models", {}) or {})
    enabled_models = [model for model in pool if str(model.get("name") or "") not in disabled_models]
    if not enabled_models:
        result.update(
            {
                "chat_status_code": 401 if disabled_models else 503,
                "error": "all_models_appid_no_auth" if disabled_models else "all_models_unavailable",
                "probe_errors": [
                    {
                        "model_name": model_name,
                        "error": reason,
                    }
                    for model_name, reason in list(disabled_models.items())[:5]
                ],
            }
        )
        return result

    prompt = '请只返回JSON: {"ok":true}'
    probe_errors = []
    probe_success = None
    auth_error_only = True

    for model in enabled_models:
        model_name = str(model.get("name") or "")
        try:
            service = AIService(model_config=model)
            response = service.get_response(prompt)
            if str(response or "").strip():
                probe_success = model_name
                break
            error_code = int(service.error_code or 0)
            error_msg = str(service.error_msg or "empty_response")
            probe_errors.append(
                {
                    "model_name": model_name,
                    "error_code": error_code,
                    "error": error_msg,
                }
            )
            if error_code not in AUTH_INVALID_ERROR_CODES or "AppIdNoAuthError" not in error_msg:
                auth_error_only = False
        except LLMBackendUnavailableError as exc:
            message = str(exc)
            probe_errors.append(
                {
                    "model_name": model_name,
                    "error": message,
                }
            )
            if "disabled" not in message.lower():
                auth_error_only = False
        except Exception as exc:
            probe_errors.append(
                {
                    "model_name": model_name,
                    "error": repr(exc),
                }
            )
            auth_error_only = False

    if probe_success:
        result.update(
            {
                "chat_status_code": 200,
                "chat_model_name": probe_success,
            }
        )
        return result

    result.update(
        {
            "chat_status_code": 401 if probe_errors and auth_error_only else 503,
            "error": "all_models_appid_no_auth" if probe_errors and auth_error_only else "all_models_unavailable",
            "probe_errors": probe_errors[:5],
        }
    )
    return result


def chat_with_glm(content, *, model=None):
    """
    Send content to the configured LLM backend and return response.
    """
    openai_config = _get_openai_compatible_config()
    if openai_config:
        requested_model = str(model or "").strip()
        if requested_model:
            requested_model = require_non_gpt_analysis_model(
                requested_model,
                setting="explicit analysis model",
            )
            openai_config = dict(openai_config)
            openai_config["model"] = requested_model
            openai_config["models"] = [requested_model]
        logger.debug(
            "Sending request to OpenAI-compatible backend (model=%s)...",
            openai_config["model"],
        )
        from src.llm_qualification_pool import QualifiedModelPool, pool_enabled
        if pool_enabled():
            import sqlite3
            try:
                pool = QualifiedModelPool(openai_config, proxies=_get_openai_compatible_proxies(openai_config["base_url"]))
                result = pool.chat(content, model=requested_model or None)
            except (OSError, sqlite3.Error, ValueError):
                raise LLMBackendUnavailableError("LLM backend unavailable: model pool state unavailable") from None
        else:
            result = _chat_with_openai_compatible(content, openai_config)
        logger.debug("OpenAI-compatible response received (len=%s).", len(result))
        stripped = _strip_json_markdown(result)
        if not str(stripped or "").strip():
            raise LLMBackendUnavailableError("LLM backend unavailable: OpenAI-compatible backend returned empty response")
        return stripped

    if model:
        raise LLMBackendUnavailableError(
            "LLM backend unavailable: explicit model routing requires the OpenAI-compatible backend"
        )
    service = AIService()
    logger.debug("Sending request to GLM-4.7...")
    result = service.get_response(content)
    logger.debug("GLM-4.7 response received (len=%s).", len(result))

    if service.error_code in AUTH_INVALID_ERROR_CODES:
        raise LLMBackendUnavailableError(
            f"LLM backend unavailable: error_code={service.error_code}, error_msg={service.error_msg or 'AppIdNoAuthError'}"
        )
    stripped = _strip_json_markdown(result)
    if not str(stripped or "").strip():
        raise LLMBackendUnavailableError("LLM backend unavailable: empty response from AI backend")
    return stripped


__all__ = ['_strip_json_markdown', 'require_non_gpt_analysis_model', '_get_openai_compatible_config', '_first_nonempty_env', '_is_local_openai_compatible_url', '_get_openai_compatible_proxies', '_chat_with_openai_compatible', 'preflight_openai_compatible_backend', 'preflight_llm_backend', 'chat_with_glm']
