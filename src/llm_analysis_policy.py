"""Dependency-free model policy shared by runtime and operator configuration."""

import re

from src.project_environment import getenv

ALLOWED_GPT_MODELS = frozenset({"gpt-6.1-sol", "gpt-6-luna"})


def gpt_models_enabled(*, reader=None):
    value = str(getenv("CROW_ANALYSIS_ALLOW_GPT", "0", reader=reader)).strip().lower()
    if value not in {"0", "1", "false", "true", "no", "yes", "off", "on", ""}:
        raise ValueError("CROW_ANALYSIS_ALLOW_GPT must be a boolean switch")
    return value in {"1", "true", "yes", "on"}


def validate_analysis_model_route(model, *, setting):
    """Validate a saved preference without granting permission to send a request."""
    normalized = str(model or "").strip()
    lowered = normalized.casefold()
    reasoning = bool(re.search(r"(?:^|[/:._-])o\d+(?:[/:._-]|$)", lowered))
    is_gpt = "gpt" in lowered or "codex" in lowered or reasoning
    if not normalized or (is_gpt and normalized not in ALLOWED_GPT_MODELS):
        raise ValueError(f"{setting} must use a non-GPT route or gpt-6.1-sol or gpt-6-luna")
    return normalized


def require_non_gpt_analysis_model(model, *, setting, allow_gpt=None):
    """Legacy name retained; request permission is checked at the runtime boundary."""
    normalized = validate_analysis_model_route(model, setting=setting)
    allowed = gpt_models_enabled() if allow_gpt is None else allow_gpt
    if type(allowed) is not bool:
        raise ValueError("GPT permission must be a boolean")
    if not allowed and normalized in ALLOWED_GPT_MODELS:
        raise ValueError(f"{setting} must use an explicit non-GPT analysis model route")
    return normalized
