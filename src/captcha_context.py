from __future__ import annotations

from tools.cdp_browser_identity import (
    browser_identity_init_script,
    build_user_agent_override,
)

DEFAULT_CDP_PAGE_TARGET_LIMIT = 12
LOCAL_MOCK_VERIFY_MODES = {
    "strict_success_text",
    "teardown_only",
    "explicit_fail",
    "near_miss",
    "retry_then_success",
}

__all__ = [
    "DEFAULT_CDP_PAGE_TARGET_LIMIT",
    "LOCAL_MOCK_VERIFY_MODES",
    "browser_identity_init_script",
    "build_user_agent_override",
]
