"""Background page ownership shared by collection stages; never compact tabs."""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from tools.browser_cdp_session import held_cdp_session
from tools.capture_budget import bounded_capture_timeout, check_capture_budget
from tools.capture_progress import mark_capture_stage
from tools.cdp_background_page import open_background_page

logger = logging.getLogger(__name__)


@dataclass
class OwnedBrowserPage:
    page: Any
    target_id: str
    preserve: bool = False


def _target_id(context, page):
    with held_cdp_session(context, page) as session:
        result = session.send("Target.getTargetInfo")
    return str(result.get("targetInfo", {}).get("targetId") or "")


def _find_owned_page(context, first_page, target_id, deadline):
    from playwright.sync_api import Error as PlaywrightError

    page = first_page
    while True:
        check_capture_budget()
        candidates = [page] + [p for p in context.pages if p is not page]
        for candidate in candidates:
            check_capture_budget()
            if candidate is None:
                continue
            try:
                actual_id = _target_id(context, candidate)
            except PlaywrightError:
                # A borrowed page may disappear while our exact owned page exists.
                check_capture_budget()
                continue
            if actual_id == target_id:
                return candidate
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            raise RuntimeError("Owned background page attachment was not confirmed")
        page = context.wait_for_event(
            "page", timeout=bounded_capture_timeout(remaining_ms)
        )


@contextmanager
def owned_background_page(context, cdp_endpoint):
    """Create once, verify the exact acknowledged ID, and clean up only that ID."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from websocket import WebSocketException

    from tools import taobao_login_health
    from tools.cdp_background_page import BackgroundPageCapacityError
    from tools.live_smoke_context import CdpEndpointUnavailableError

    target_id = ""
    owned = None
    operation_failed = True
    deadline = time.monotonic() + bounded_capture_timeout(5000) / 1000
    try:
        first_page = None
        try:
            with context.expect_page(timeout=bounded_capture_timeout(5000)) as pending:
                try:
                    target = open_background_page(cdp_endpoint, "about:blank")
                except BackgroundPageCapacityError:
                    raise
                except (OSError, RuntimeError, WebSocketException) as error:
                    raise CdpEndpointUnavailableError(
                        cdp_endpoint, "open_background_page", error
                    ) from error
                target_id = str(target.get("id") or "")
                if not target_id:
                    raise RuntimeError("Background page has no acknowledged target ID")
            first_page = pending.value
        except PlaywrightTimeoutError:
            if not target_id:
                raise
            # A lost event is recoverable only by the acknowledged exact ID.
        try:
            page = _find_owned_page(context, first_page, target_id, deadline)
        except PlaywrightError as error:
            raise CdpEndpointUnavailableError(
                cdp_endpoint, "attach_background_page", error
            ) from error
        owned = OwnedBrowserPage(page, target_id)
        yield owned
        operation_failed = False
    finally:
        if target_id and (owned is None or not owned.preserve):
            mark_capture_stage("page_close")
            try:
                if not taobao_login_health.close_cdp_target(cdp_endpoint, target_id):
                    raise RuntimeError(
                        "Owned background page cleanup was not confirmed"
                    )
            except Exception as error:
                if not operation_failed:
                    raise
                logger.warning("Owned page cleanup failed (%s)", type(error).__name__)
