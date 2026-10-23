"""Keep bounded per-page failure evidence after cycle summaries are replaced."""

import json
import time
from pathlib import Path

from tools.safe_exception_diagnostics import safe_exception_text, safe_exception_traceback


def record_seed_exception(output_dir: Path, exc: Exception, *, stage: str) -> None:
    event = {
        "event": "seed_collector_page_exception",
        "observed_at_epoch": time.time(),
        "stage": stage,
        "error": safe_exception_text(exc),
        "traceback": safe_exception_traceback(exc),
    }
    # Never include task URLs, response bodies, exception messages or locals.
    try:
        print(json.dumps(event, ensure_ascii=False), flush=True)
    except OSError:
        pass
    try:
        (output_dir / "seed_collector_last_failure.json").write_text(
            json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        # A diagnostic write failure must not strand the claimed page lease.
        pass
