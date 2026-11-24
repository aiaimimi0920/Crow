from __future__ import annotations

import logging
import os
import re
import threading
import time
from urllib.parse import urlparse

from src.llm_analysis_policy import (
    require_non_gpt_analysis_model,
    validate_analysis_model_route,
)
from src.llm_model_selector import (
    AUTH_INVALID_ERROR_CODES,
    LLMBackendUnavailableError,
)
from src.llm_preflight_probe import (
    preflight_llm_backend,
    preflight_openai_compatible_backend,
)
from src.llm_rest_transport import _get_http_session, _message_text
from src.llm_websocket import AIService
from src.project_environment import getenv as project_getenv

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
        or "glm-5-2"
    )
    candidate_text = os.environ.get("OPENAI_MODEL_CANDIDATES") or ""
    models = []
    for candidate in [primary_model, *re.split(r"[;,]", candidate_text)]:
        normalized = str(candidate or "").strip()
        if normalized:
            normalized = validate_analysis_model_route(
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
    reasoning_effort = (
        str(os.environ.get("OPENAI_REASONING_EFFORT") or "").strip().lower()
    )
    if reasoning_effort:
        allowed_reasoning_efforts = {
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        }
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
    explicit_http_proxy = _first_nonempty_env(
        "OPENAI_HTTP_PROXY", "CROW_LLM_HTTP_PROXY"
    )
    explicit_https_proxy = _first_nonempty_env(
        "OPENAI_HTTPS_PROXY", "CROW_LLM_HTTPS_PROXY"
    )
    if (
        base_url
        and _is_local_openai_compatible_url(base_url)
        and not (fallback_proxy or explicit_http_proxy or explicit_https_proxy)
    ):
        return {}

    http_proxy = (
        explicit_http_proxy or _first_nonempty_env("CROW_HTTP_PROXY") or fallback_proxy
    )
    https_proxy = (
        explicit_https_proxy
        or _first_nonempty_env("CROW_HTTPS_PROXY")
        or fallback_proxy
        or http_proxy
    )
    proxies = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


try:
    _REST_CONCURRENCY = max(int(os.environ.get("CROW_LLM_REST_CONCURRENCY", "6")), 1)
except ValueError:
    _REST_CONCURRENCY = 6
_REST_SEMAPHORE = threading.BoundedSemaphore(_REST_CONCURRENCY)


def _chat_with_openai_compatible(content, config):
    from src.llm_evidence_prompt import request_messages
    from src.llm_request_policy import (
        MAX_OUTPUT_TOKENS,
        MAX_RETRY_WAIT_SECONDS,
        retry_delay,
    )

    url = f"{config['base_url']}/chat/completions"
    proxies = _get_openai_compatible_proxies(config["base_url"])
    session = _get_http_session(config["base_url"], proxies, config["api_key"])
    max_retries = max(int(config.get("max_retries", 3)), 1)
    models = list(config.get("models") or [config["model"]])
    response = None
    forbidden_models = set()
    empty_models = set()
    policy_blocked_models = set()
    policy_blocked_error: ValueError | None = None
    for attempt in range(1, max_retries + 1):
        wait_seconds = min(2 ** (attempt - 1), 8)
        for model in models:
            if model in (forbidden_models | empty_models | policy_blocked_models):
                continue
            try:
                require_non_gpt_analysis_model(model, setting="OpenAI request model")
            except ValueError as exc:
                policy_blocked_models.add(model)
                if policy_blocked_error is None:
                    policy_blocked_error = exc
                continue
            request_payload = {
                "model": model,
                "messages": request_messages(content),
                "temperature": 0,
                "max_tokens": MAX_OUTPUT_TOKENS,
            }
            if config.get("reasoning_effort"):
                request_payload["reasoning_effort"] = config["reasoning_effort"]
            with _REST_SEMAPHORE:
                response = session.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {config['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                    timeout=config["timeout"],
                )
            session.cookies.clear()
            status_code = getattr(response, "status_code", None)
            if status_code is not None and status_code < 400:
                text, finish_reason = _message_text(response)
                if text:
                    config["last_successful_model"] = model
                    return text
                empty_models.add(model)
                logger.warning(
                    "LLM model %s returned empty content (finish_reason=%s); "
                    "trying next candidate without backoff",
                    model,
                    finish_reason,
                )
                continue
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
        if attempt >= max_retries or len(
            forbidden_models | empty_models | policy_blocked_models
        ) >= len(models):
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
        if policy_blocked_error is not None:
            raise policy_blocked_error
        raise LLMBackendUnavailableError(
            "LLM backend unavailable: no OpenAI-compatible model candidates"
        )
    response.raise_for_status()
    raise ValueError(
        "OpenAI-compatible response missing message content "
        f"(models tried: {', '.join(models)}; empty: {', '.join(sorted(empty_models)) or 'none'})"
    )


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
                pool = QualifiedModelPool(
                    openai_config,
                    proxies=_get_openai_compatible_proxies(openai_config["base_url"]),
                )
                result = pool.chat(content, model=requested_model or None)
            except (OSError, sqlite3.Error, ValueError):
                raise LLMBackendUnavailableError(
                    "LLM backend unavailable: model pool state unavailable"
                ) from None
        else:
            result = _chat_with_openai_compatible(content, openai_config)
        logger.debug("OpenAI-compatible response received (len=%s).", len(result))
        stripped = _strip_json_markdown(result)
        if not str(stripped or "").strip():
            raise LLMBackendUnavailableError(
                "LLM backend unavailable: OpenAI-compatible backend returned empty response"
            )
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
        raise LLMBackendUnavailableError(
            "LLM backend unavailable: empty response from AI backend"
        )
    return stripped


__all__ = [
    "_chat_with_openai_compatible",
    "_first_nonempty_env",
    "_get_openai_compatible_config",
    "_get_openai_compatible_proxies",
    "_is_local_openai_compatible_url",
    "_strip_json_markdown",
    "chat_with_glm",
    "preflight_llm_backend",
    "preflight_openai_compatible_backend",
    "require_non_gpt_analysis_model",
]
