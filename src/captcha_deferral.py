"""Preserve unconfirmed operations and finish their state under the solve lock."""

from contextlib import contextmanager

from .captcha_nc_retry import NCRetryDeferred


class TargetNavigationUnconfirmed(Exception):
    """Navigation may have reached the page; retain it without replay this solve."""

    reason = "cdp_unavailable"


@contextmanager
def preserve_unconfirmed_target(solver, budget):
    try:
        yield
    except (NCRetryDeferred, TargetNavigationUnconfirmed) as deferred:
        # No fallback, navigation or page cleanup may replay the command.
        solver.last_failure_reason = (
            budget.reason
            if budget.stopped(solver._cancel_requested)
            else deferred.reason
        )
        solver._close_solver_ws()
        raise
