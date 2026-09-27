from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from html import unescape
from pathlib import Path
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlparse, urlsplit, urlunsplit

import requests
import websocket

from src.cdp_cookie_transport import (
    DEFAULT_CDP_CONNECT_TIMEOUT_MS,
    DEFAULT_CDP_RECONNECT_ATTEMPTS,
    DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS,
    DEFAULT_COOKIE_ORIGINS,
    DEFAULT_USER_AGENT,
)

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    sync_playwright = None

DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"
DEFAULT_TARGET_URL = (
    "https://sf.taobao.com/list/50025969__2.htm"
    "?location_code=110101&st_param=2&auction_start_seg=-1&page=1"
)
from src.collection.adapters.taobao_health import (
    SENSITIVE_INLINE_PATTERNS as _SENSITIVE_INLINE_PATTERNS,
)
from src.collection.adapters.taobao_list_probe import (
    DEFAULT_ACCEPT_LANGUAGE,
    DEFAULT_NAVIGATION_ACCEPT,
    _SCRIPT_RE,
)


__all__ = tuple(name for name in globals() if not name.startswith("__"))
