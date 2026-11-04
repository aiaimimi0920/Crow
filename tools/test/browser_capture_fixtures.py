"""Offline page lease for focused capture/session/retention regressions."""

import logging
from contextlib import contextmanager

from tools.browser_owned_page import OwnedBrowserPage
from tools.capture_progress import mark_capture_stage


def install_owned_page_fixture(monkeypatch):
    @contextmanager
    def lease(context, _endpoint):
        owned = OwnedBrowserPage(context.new_page(), "owned-fixture")
        failed = True
        try:
            yield owned
            failed = False
        finally:
            if not owned.preserve:
                mark_capture_stage("page_close")
                try:
                    owned.page.close()
                except Exception as error:
                    if not failed:
                        raise
                    logging.getLogger(__name__).warning(
                        "Owned page cleanup failed (%s)", type(error).__name__
                    )

    monkeypatch.setattr("tools.browser_target_capture.owned_background_page", lease)
