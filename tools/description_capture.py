"""Bound optional description enrichment without leaving timed-out work alive."""

import contextlib
import json
import logging
import math
import sys

logger = logging.getLogger(__name__)
DEFAULT_DESCRIPTION_SECONDS = 20.0


def fetch_description_with_deadline(html, *, timeout=DEFAULT_DESCRIPTION_SECONDS):
    from bs4 import BeautifulSoup

    from src.llm_text_extraction import _parse_description_data_link
    from tools.detail_browser_capture import run_capture_process

    seconds = float(timeout)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Invalid description capture deadline")
    try:
        if not html or not _parse_description_data_link(
            BeautifulSoup(html, "html.parser")
        ):
            return None
        output = run_capture_process(
            [sys.executable, "-B", "-m", "tools.description_capture"],
            json.dumps({"html": html, "timeout": seconds}, ensure_ascii=False).encode(
                "utf-8"
            ),
            timeout_seconds=seconds,
        )
        value = json.loads(output)
        if not isinstance(value, dict) or "text" not in value:
            raise ValueError("Invalid description capture reply")
        text = value["text"]
        if text is not None and not isinstance(text, str):
            raise ValueError("Invalid description capture text")
        if not text:
            logger.warning(
                "[AREA_FALLBACK_WARN] description-data capture returned no text"
            )
        return text or None
    except Exception as error:  # noqa: BLE001 -- optional evidence remains unknown
        logger.warning(
            "[AREA_FALLBACK_WARN] description-data capture unavailable (%s)",
            type(error).__name__,
        )
        return None


def description_reply(fetch, request):
    """Keep the legacy decoder and fetch behavior inside the owned process."""
    with contextlib.redirect_stdout(sys.stderr):
        text = fetch(request["html"], timeout=request["timeout"])
    return {"text": text}


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    request = json.load(sys.stdin)
    from src.llm_text_extraction import fetch_description_data_text

    reply = description_reply(fetch_description_data_text, request)
    print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
