"""Private stdin/stdout protocol for one attached-browser detail capture."""

from __future__ import annotations

import contextlib
import json
import sys


def capture_reply(capture, request):
    from src.project_environment import EnvironmentAliasConflict
    from tools.live_smoke_context import (
        CdpEndpointUnavailableError,
        DetailChallengeError,
    )
    from tools.safe_exception_diagnostics import safe_exception_details

    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = capture(request["seed"], cdp_endpoint=request["cdp_endpoint"])
        return {"kind": "ok", "result": result}
    except DetailChallengeError as error:
        return {
            "kind": "challenge",
            "operation": error.operation,
            "challenge_url": error.challenge_url,
        }
    except CdpEndpointUnavailableError as error:
        return {"kind": "cdp", "operation": error.operation}
    except EnvironmentAliasConflict as error:
        # This exception's message contains configuration keys, never values.
        return {"kind": "configuration", "message": str(error)}
    # Private protocol boundary: never serialize an unknown exception's raw text.
    except Exception as error:  # noqa: BLE001
        return {"kind": "error", "diagnostic": safe_exception_details(error)}


def main():
    # This is also the Windows job-assignment gate: no driver starts before input.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    request = json.load(sys.stdin)
    from tools.live_batch_smoke import _fetch_detail_with_browser_attached

    response = capture_reply(_fetch_detail_with_browser_attached, request)
    print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
