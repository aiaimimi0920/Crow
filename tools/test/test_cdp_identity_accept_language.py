"""CDP consumes ordered language codes, not an already weighted HTTP header."""

import pytest

from tools.cdp_browser_identity import build_user_agent_override

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152.0.0.0"
FULL_VERSION = "152.0.7977.64"


@pytest.mark.parametrize("options", [{}, {"accept_language": ""}])
def test_default_cdp_language_list_does_not_preweight_chromium_header(options):
    payload = build_user_agent_override(USER_AGENT, FULL_VERSION, **options)

    assert payload["acceptLanguage"] == "zh-CN,zh"
    assert all(";" not in language for language in payload["acceptLanguage"].split(","))


def test_explicit_cdp_language_list_keeps_its_order():
    payload = build_user_agent_override(
        USER_AGENT, FULL_VERSION, accept_language="en-US,en,zh-CN"
    )

    assert payload["acceptLanguage"] == "en-US,en,zh-CN"
    assert payload["userAgent"] == USER_AGENT
    assert payload["userAgentMetadata"]["fullVersion"] == FULL_VERSION
