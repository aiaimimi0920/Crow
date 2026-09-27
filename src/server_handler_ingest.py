from __future__ import annotations

import logging
import os  # noqa: F401 - direct-module upload filesystem
import sys
import time  # noqa: F401 - direct-module captcha report clock
from typing import cast

from .captcha_report_handler import CaptchaReportHost, bind_captcha_reports
from .detail_dispatch_handlers import DetailDispatchHost, bind_detail_dispatch
from .detail_ingest_handlers import DetailIngestHost, bind_detail_ingest
from .screen_handlers import ScreenHost, bind_screen
from .server_context import (
    AVM_SERVICE,  # noqa: F401 - direct-module native host dependency
    CHALLENGE_SCOPES,  # noqa: F401 - direct-module captcha report host
    DATA_DIR,  # noqa: F401 - direct-module native host dependency
    DB_REPOSITORY,  # noqa: F401 - direct-module native host dependency
    DEFAULT_MARGIN_THRESHOLD,  # noqa: F401 - direct-module native host dependency
    DISPATCH_COOLDOWN_SECONDS,  # noqa: F401 - direct-module detail dispatch host
    RUNTIME,  # noqa: F401 - direct-module captcha report host
    build_alert_blockers,  # noqa: F401 - direct-module native host dependency
    get_effective_alert_threshold,  # noqa: F401 - direct-module native host dependency
)
from .server_handler_compatibility import (
    HandlerCompatibilityHost,
    bind_handler_compatibility,
)
from .upload_handler import UPLOAD_ITEM_ID_PATTERN, UploadHost, bind_uploads

logger = logging.getLogger(__name__)

_screen = bind_screen(cast(ScreenHost, sys.modules[__name__]))
_run_analysis_screen = _screen._run_analysis_screen
_post_analysis_screen = _screen._post_analysis_screen

_post_captcha_report = bind_captcha_reports(
    cast(CaptchaReportHost, sys.modules[__name__])
)._post_captcha_report

_http_adapters = bind_handler_compatibility(
    cast(HandlerCompatibilityHost, sys.modules[__name__])
)
_post_client_log = _http_adapters._post_client_log
_server_post_fallback = _http_adapters._server_post_fallback

_UPLOAD_ITEM_ID_PATTERN = UPLOAD_ITEM_ID_PATTERN

_uploads = bind_uploads(cast(UploadHost, sys.modules[__name__]))
_resolve_upload_target = _uploads._resolve_upload_target
_post_upload = _uploads._post_upload

_detail_ingest = bind_detail_ingest(cast(DetailIngestHost, sys.modules[__name__]))
_post_detail_update_item = _detail_ingest._post_detail_update_item
_post_detail_html = _detail_ingest._post_detail_html

_post_detail_next_visit = bind_detail_dispatch(
    cast(DetailDispatchHost, sys.modules[__name__])
)._post_detail_next_visit

__all__ = [  # noqa: RUF022 - preserve legacy export ordering
    "_UPLOAD_ITEM_ID_PATTERN",
    "_resolve_upload_target",
    "_run_analysis_screen",
    "_post_analysis_screen",
    "_post_captcha_report",
    "_post_client_log",
    "_post_upload",
    "_post_detail_update_item",
    "_post_detail_next_visit",
    "_post_detail_html",
    "_server_post_fallback",
]
