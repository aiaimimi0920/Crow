"""Bounded payload readiness polling independent of the collection stage."""

import time

from tools.capture_budget import bounded_capture_timeout, check_capture_budget


def wait_for_target_ready(
    page, *, is_challenge, is_ready, timeout_ms, poll_interval_ms
):
    timeout = max(int(timeout_ms), 1)
    interval = max(int(poll_interval_ms), 1)
    deadline = time.monotonic() + timeout / 1000
    max_polls = max((timeout + interval - 1) // interval, 1)
    last_html = ""
    for index in range(max_polls + 1):
        check_capture_budget()
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if index and remaining_ms <= 0:
            break
        last_html = str(
            page.locator("html").inner_html(
                timeout=bounded_capture_timeout(max(1, min(remaining_ms, 5000)))
            )
            or ""
        )
        check_capture_budget()
        url = str(page.url or "")
        if is_challenge(last_html, url) or is_ready(last_html, url):
            return last_html
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if index >= max_polls or remaining_ms <= 0:
            break
        page.wait_for_timeout(bounded_capture_timeout(min(interval, remaining_ms)))
    return last_html
