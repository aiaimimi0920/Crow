from __future__ import annotations

import logging
import os  # noqa: F401 - direct-module lifecycle host
import sys
import time  # noqa: F401 - direct-module lifecycle host
from typing import cast

from .server_context import CHALLENGE_SCOPES, RUNTIME  # noqa: F401 - direct-module host
from .server_handler_compatibility import (
    HandlerCompatibilityHost,
    bind_handler_compatibility,
)
from .server_http_responses import (
    _redact_error_details,
    _write_json_response,
    send_error_json,
    send_invalid_request_body,
    send_json,
)
from .solver_execution_guard import SolverExecutionGuard, SolverExecutionHost
from .solver_run_binding import bind_solver_run
from .solver_run_contracts import SolverRunHost

logger = logging.getLogger(__name__)

_compatibility = bind_handler_compatibility(
    cast(HandlerCompatibilityHost, sys.modules[__name__])
)
update_file = _compatibility.update_file
log_message = _compatibility.log_message

_execution_guard = SolverExecutionGuard(
    cast(SolverExecutionHost, sys.modules[__name__])
)
_solver_execution_is_current = _execution_guard._solver_execution_is_current
_solver_execution_resumed = _execution_guard._solver_execution_resumed
_solver_execution_cancelled = _execution_guard._solver_execution_cancelled
_wait_for_solver_manual_poll = _execution_guard._wait_for_solver_manual_poll

run_solver = bind_solver_run(cast(SolverRunHost, sys.modules[__name__])).run_solver

__all__ = [  # noqa: RUF022 - retain legacy publication order
    "_write_json_response",
    "_redact_error_details",
    "send_json",
    "send_error_json",
    "send_invalid_request_body",
    "update_file",
    "_solver_execution_is_current",
    "_solver_execution_resumed",
    "_solver_execution_cancelled",
    "_wait_for_solver_manual_poll",
    "run_solver",
    "log_message",
]
