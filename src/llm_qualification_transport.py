"""Bound response size and body duration without logging provider payloads."""
import json
import time
from email.utils import parsedate_to_datetime

from src.llm_model_selector import LLMBackendUnavailableError


class ModelHttpError(LLMBackendUnavailableError):
    def __init__(self, status_code, retry_after_seconds):
        super().__init__(f"LLM backend unavailable: HTTP {status_code}")
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


class ModelRateLimitedError(ModelHttpError):
    def __init__(self, retry_after_seconds):
        super().__init__(429, retry_after_seconds)


def _retry_after_seconds(response):
    value = getattr(response, "headers", {}).get("Retry-After", "")
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return 60


def request_json(session, method, url, *, timeout, max_bytes, **kwargs):
    started = time.monotonic()
    cookies = getattr(session, "cookies", None)
    if cookies is not None:
        cookies.clear()
    response = getattr(session, method)(url, timeout=timeout, stream=True,
                                        allow_redirects=False, **kwargs)
    try:
        if response.status_code == 429:
            raise ModelRateLimitedError(_retry_after_seconds(response))
        if not 200 <= response.status_code < 300:
            raise ModelHttpError(response.status_code, _retry_after_seconds(response))
        chunks = bytearray()
        # A whole buffered chunk can take indefinitely under a slow trickle.
        for chunk in response.iter_content(chunk_size=1):
            chunks.extend(chunk)
            if len(chunks) > max_bytes or time.monotonic() - started > timeout:
                raise LLMBackendUnavailableError("LLM backend unavailable: response limit exceeded")
        return json.loads(chunks.decode("utf-8"))
    finally:
        response.close()
        if cookies is not None:
            cookies.clear()
