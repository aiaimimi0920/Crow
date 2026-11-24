"""Health and capability preflight probes for OpenAI-compatible and legacy LLM backends."""

from __future__ import annotations

import requests

from src.llm_analysis_policy import require_non_gpt_analysis_model
from src.llm_config import get_model_pool
from src.llm_model_selector import (
    AUTH_INVALID_ERROR_CODES,
    LLMBackendUnavailableError,
    get_model_selector,
)
from src.llm_websocket import AIService


def preflight_openai_compatible_backend(timeout=15.0, *, check_chat=False):
    from src.llm_openai_compatible import (
        _get_openai_compatible_config,
        _get_openai_compatible_proxies,
    )
    from src.llm_qualification_pool import QualifiedModelPool, pool_enabled

    config = _get_openai_compatible_config()
    if not config:
        return {"enabled": False}

    if pool_enabled():
        import sqlite3

        allowed: list[str] | None = None
        try:
            pool = QualifiedModelPool(
                config, proxies=_get_openai_compatible_proxies(config["base_url"])
            )
            allowed = pool.allowed_models()
            models = pool.refresh_in_background() if allowed else []
        except (OSError, sqlite3.Error, ValueError):
            models = []
        if allowed == []:
            return {
                "enabled": True,
                "status_code": 403,
                "chat_status_code": 403,
                "qualified_models": [],
                "model_pool": "no_eligible_models",
                "reason": "no_eligible_analysis_models",
            }
        return {
            "enabled": True,
            "status_code": 200 if models else 503,
            "chat_status_code": 200 if models else 503,
            "qualified_models": models,
            "model_pool": "ready" if models else "exhausted_or_probing",
        }

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
        policy_excluded = 0
        for model in models:
            try:
                require_non_gpt_analysis_model(model, setting="OpenAI preflight model")
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
            except ValueError:
                policy_excluded += 1
                result.setdefault("probe_errors", []).append(
                    {"model_name": model, "error_type": "PolicyExcluded"}
                )
                continue
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
        chat_status = getattr(chat_response, "status_code", None)
        if chat_status is None and policy_excluded == len(models) and models:
            chat_status = 403
            result["reason"] = "no_eligible_analysis_models"
        result.update(
            {
                "chat_url": chat_url,
                "chat_status_code": chat_status,
            }
        )
        if len(models) > 1:
            result["chat_model_name"] = chat_model
    return result


def preflight_llm_backend(timeout=15.0, *, check_chat=False):
    from src.llm_openai_compatible import _get_openai_compatible_config

    config = _get_openai_compatible_config()
    if config:
        result = preflight_openai_compatible_backend(
            timeout=timeout, check_chat=check_chat
        )
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
    enabled_models = [
        model for model in pool if str(model.get("name") or "") not in disabled_models
    ]
    if not enabled_models:
        result.update(
            {
                "chat_status_code": 401 if disabled_models else 503,
                "error": "all_models_appid_no_auth"
                if disabled_models
                else "all_models_unavailable",
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
            if (
                error_code not in AUTH_INVALID_ERROR_CODES
                or "AppIdNoAuthError" not in error_msg
            ):
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
        except Exception as exc:  # noqa: BLE001 -- preserve legacy websocket probe error envelope
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
            "error": "all_models_appid_no_auth"
            if probe_errors and auth_error_only
            else "all_models_unavailable",
            "probe_errors": probe_errors[:5],
        }
    )
    return result


__all__ = [
    "preflight_llm_backend",
    "preflight_openai_compatible_backend",
]
