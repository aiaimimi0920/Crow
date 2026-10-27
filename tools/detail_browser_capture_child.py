"""Private stdin/stdout protocol for one attached-browser detail capture."""

from __future__ import annotations

import contextlib
import json
import sys


def capture_reply(capture, request):
    from src.project_environment import EnvironmentAliasConflict
    from tools.capture_budget import capture_budget
    from tools.capture_failure_diagnostics import capture_error_diagnostic
    from tools.live_smoke_context import (
        CdpEndpointUnavailableError,
        DetailChallengeError,
    )

    try:
        with (
            capture_budget(request.get("deadline_monotonic")),
            contextlib.redirect_stdout(sys.stderr),
        ):
            result = capture(request["seed"], cdp_endpoint=request["cdp_endpoint"])
        return {"kind": "ok", "result": result}
    except DetailChallengeError as error:
        return {
            "kind": "challenge",
            "operation": error.operation,
            "challenge_url": error.challenge_url,
        }
    except CdpEndpointUnavailableError as error:
        return {
            "kind": "cdp",
            "operation": error.operation,
            "diagnostic": capture_error_diagnostic(error.cause),
        }
    except EnvironmentAliasConflict as error:
        # This exception's message contains configuration keys, never values.
        return {"kind": "configuration", "message": str(error)}
    # Private protocol boundary: never serialize an unknown exception's raw text.
    except Exception as error:  # noqa: BLE001
        return {"kind": "error", "diagnostic": capture_error_diagnostic(error)}


def main():
    # This is also the Windows job-assignment gate: no driver starts before input.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    request = json.load(sys.stdin)
    from tools.capture_progress import capture_progress, mark_capture_stage

    with capture_progress():
        mark_capture_stage("helper_import")
        from tools.live_batch_smoke import _fetch_detail_with_browser_attached

        mark_capture_stage("capture_start")
        response = capture_reply(_fetch_detail_with_browser_attached, request)
        mark_capture_stage("reply_write")
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
