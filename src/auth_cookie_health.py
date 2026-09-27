"""Cookie snapshot health aggregation independent of tool facades."""

from src.cdp_cookie_transport import resolve_cdp_user_agent
from src.collection.adapters.taobao_health import classify_taobao_health
from src.collection.adapters.taobao_list_probe import (
    build_session_from_playwright_cookies,
    probe_seed_page,
)


def probe_cookie_snapshot_health(
    cookies: list[dict[str, object]],
    sample_urls: list[str],
    *,
    cdp_endpoint: str = "",
) -> dict[str, object]:
    session = build_session_from_playwright_cookies(cookies)
    user_agent = resolve_cdp_user_agent(cdp_endpoint)
    sample_results: list[dict[str, object]] = []
    healthy_samples = 0
    for url in sample_urls:
        try:
            summary = probe_seed_page(
                url,
                cookies=cookies,
                session=session,
                timeout=15,
                user_agent=user_agent,
            )
            classification = classify_taobao_health(
                "",
                final_url=str(summary.get("final_url") or url),
                list_summary=summary,
                payload_present=summary.get("has_script") is True,
            )
            result = {
                "check_url": url,
                "status": classification.get("status"),
                "healthy": bool(classification.get("healthy")),
                "final_url": classification.get("final_url"),
                "http_status": summary.get("status"),
                "has_script": summary.get("has_script"),
                "item_count": summary.get("item_count"),
                "body_has_login": summary.get("body_has_login"),
                "body_has_captcha": summary.get("body_has_captcha"),
                "body_has_punish": summary.get("body_has_punish"),
                "body_has_challenge": summary.get("body_has_challenge"),
            }
        except Exception as error:  # noqa: BLE001 - each sample reports its own failure
            result = {
                "check_url": url,
                "status": "probe_error",
                "healthy": False,
                "error": repr(error),
            }
        if result.get("healthy") is True:
            healthy_samples += 1
        sample_results.append(result)

    return {
        "healthy": healthy_samples > 0,
        "healthy_samples": healthy_samples,
        "sample_count": len(sample_results),
        "sample_results": sample_results,
    }
