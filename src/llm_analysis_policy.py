"""Dependency-free model policy shared by runtime and operator configuration."""
import re

from src.project_environment import getenv


def gpt_models_enabled(*, reader=None):
    value = str(getenv("CROW_ANALYSIS_ALLOW_GPT", "0", reader=reader)).strip().lower()
    if value not in {"0", "1", "false", "true", "no", "yes", "off", "on", ""}:
        raise ValueError("CROW_ANALYSIS_ALLOW_GPT must be a boolean switch")
    return value in {"1", "true", "yes", "on"}


def require_non_gpt_analysis_model(model, *, setting, allow_gpt=None):
    """Legacy public name retained; GPT requires an explicit runtime/config opt-in."""
    normalized = str(model or "").strip()
    lowered = normalized.casefold()
    reasoning = bool(re.search(r"(?:^|[/:._-])o\d+(?:[/:._-]|$)", lowered))
    allowed = gpt_models_enabled() if allow_gpt is None else allow_gpt
    if type(allowed) is not bool:
        raise ValueError("GPT permission must be a boolean")
    if not normalized or (not allowed and ("gpt" in lowered or "codex" in lowered or reasoning)):
        raise ValueError(f"{setting} must use an explicit non-GPT analysis model route")
    return normalized
