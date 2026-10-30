"""Bounded NC recovery sampling, without issuing retry clicks or navigation."""

from .captcha_verification import ready_target_matches


def nc_retry_outcome(solver, timeout_seconds, *, clock):
    deadline = clock() + max(float(timeout_seconds or 0), 0.5)
    bound_target = solver._solver_target_scope(solver.target_url) in {"seed", "detail"}
    stable_slider_signature = None
    stable_slider_samples = 0
    summary = {}
    while clock() < deadline:
        if solver._stop_if_cancelled():
            return {"cancelled": True}
        summary = solver._refresh_challenge_summary({})
        if summary.get("probeFailed"):
            return {"probeFailed": True, "summary": summary}
        if summary.get("readyState") == "loading":
            stable_slider_signature = None
            stable_slider_samples = 0
            solver._wait_interruptibly(0.35)
            continue
        if bound_target and not ready_target_matches(summary, solver.target_url):
            # Stable geometry cannot prove that a replacement document still
            # belongs to this request. Do not replay or click old coordinates.
            return {"targetUnavailable": True, "summary": summary}
        if summary.get("authenticatedPage"):
            return {"authenticated": True, "summary": summary}
        if summary.get("explicitFailure"):
            stable_slider_signature = None
            stable_slider_samples = 0
            solver._wait_interruptibly(0.35)
            continue
        slider = solver._find_slider(max_retries=1, retry_delay=0)
        if slider:
            signature = tuple(
                round(float(slider.get(key) or 0), 1)
                for key in ("x", "y", "width", "height")
            )
            if signature == stable_slider_signature:
                stable_slider_samples += 1
            else:
                stable_slider_signature = signature
                stable_slider_samples = 1
            if stable_slider_samples >= 3:
                return {"slider": slider, "summary": summary}
        else:
            stable_slider_signature = None
            stable_slider_samples = 0
        solver._wait_interruptibly(0.35)
    if summary.get("readyState") == "loading":
        return {"authenticated": False, "loading": True, "summary": summary}
    return {"authenticated": False}
