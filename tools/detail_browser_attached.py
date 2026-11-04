"""Detail adapter for the shared collection-browser capture lifecycle."""

from functools import partial

from src.collection.adapters.taobao_auth_target import browser_target_matches
from src.collection.adapters.taobao_detail_auth import detail_payload_authenticated
from tools.browser_target_capture import BrowserTargetChallenge, capture_attached_target


def capture_attached_detail(
    seed,
    *,
    cdp_endpoint,
    connect_browser,
    detach_browser,
    is_login_target,
    is_challenge,
    is_login,
    challenge_error,
    configure_page,
    wait_for_detail,
):
    target_url = seed.get("url")
    if not target_url:
        raise RuntimeError("seed missing detail url")
    try:
        return capture_attached_target(
            target_url,
            cdp_endpoint=cdp_endpoint,
            matches=partial(browser_target_matches, "detail", target_url),
            connect_browser=connect_browser,
            detach_browser=detach_browser,
            is_login_target=is_login_target,
            is_challenge=is_challenge,
            is_login=is_login,
            configure_page=configure_page,
            wait_for_ready=wait_for_detail,
            payload_authenticated=partial(
                detail_payload_authenticated, target_url=target_url
            ),
            label="detail",
        )
    except BrowserTargetChallenge as error:
        raise challenge_error(error.operation, error.challenge_url) from None
