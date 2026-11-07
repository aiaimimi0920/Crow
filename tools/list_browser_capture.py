"""Isolate list capture when the caller already owns a running asyncio loop."""

import json
import sys
import time

from tools.detail_browser_capture import (
    CLEANUP_SECONDS,
    DEFAULT_CAPTURE_SECONDS,
    decode_capture_reply,
    run_capture_process,
)


def capture_list_with_deadline(target_url, *, cdp_endpoint):
    # Reuse the detail helper's deadline, process ownership and typed IPC. The
    # child still uses the very same attached-target lifecycle as normal lists.
    request = json.dumps(
        {
            "seed": {"url": target_url},
            "cdp_endpoint": cdp_endpoint,
            "deadline_monotonic": time.monotonic()
            + DEFAULT_CAPTURE_SECONDS
            - CLEANUP_SECONDS,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    output = run_capture_process(
        [sys.executable, "-B", "-m", "tools.list_browser_capture"], request
    )
    html, final_url, _, _ = decode_capture_reply(output, cdp_endpoint=cdp_endpoint)
    return html, final_url


def _capture(seed, *, cdp_endpoint):
    from tools.live_batch_smoke import fetch_browser_navigation_list_page

    html, final_url = fetch_browser_navigation_list_page(cdp_endpoint, seed["url"])
    return html, final_url, len(html.encode("utf-8")), "browser_navigation"


def main():
    # stdin gates driver startup until the parent assigns its Windows job.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    request = json.load(sys.stdin)
    from tools.capture_progress import capture_progress, mark_capture_stage
    from tools.detail_browser_capture_child import capture_reply

    with capture_progress():
        mark_capture_stage("capture_start")
        response = capture_reply(_capture, request)
        mark_capture_stage("reply_write")
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
