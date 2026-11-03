"""Thread-owned REST pools and final assistant response decoding."""

import json
import threading

import requests

_HTTP_LOCAL = threading.local()


def _get_http_session(base_url, proxies, api_key):
    """Keep one bounded, credential-isolated connection pool per worker thread."""
    import hashlib

    key = (
        base_url,
        tuple(sorted((proxies or {}).items())),
        hashlib.sha256(api_key.encode("utf-8")).digest(),
        requests.Session,
    )
    previous = getattr(_HTTP_LOCAL, "entry", None)
    if previous is not None and previous[0] == key:
        return previous[1]
    if previous is not None:
        previous[1].close()
    session = requests.Session()
    session.trust_env = False
    session.proxies = dict(proxies or {})
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=2, pool_maxsize=2, max_retries=0
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    _HTTP_LOCAL.entry = (key, session)
    return session


def _message_text(response):
    """Only final assistant content is evidence; reasoning is not an answer."""
    raw = getattr(response, "content", None)
    payload = (
        json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else response.json()
    )
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None, None
    choice = choices[0]
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") in (None, "text")
            and isinstance(part.get("text"), str)
        )
    text = content.strip() if isinstance(content, str) else None
    return text or None, choice.get("finish_reason")
