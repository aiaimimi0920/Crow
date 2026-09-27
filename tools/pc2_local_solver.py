from __future__ import annotations

import importlib as _importlib
import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

_IMPLEMENTATION_MODULES = (
    "tools.pc2_solver_context",
    "tools.pc2_solver_transport",
    "tools.pc2_solver_scope_policy",
    "tools.pc2_solver_scope",
    "tools.pc2_solver_auth",
    "tools.pc2_solver_state_store",
    "tools.pc2_solver_retry_state",
    "tools.pc2_solver_fallback",
    "tools.pc2_solver_auth_pending",
    "tools.pc2_solver_cdp",
    "tools.pc2_solver_manual_handoff",
    "tools.pc2_solver_execution",
    "tools.pc2_solver_loop_control",
    "tools.pc2_solver_loop",
)


_loaded_modules = [_importlib.import_module(name) for name in _IMPLEMENTATION_MODULES]
for _module in _loaded_modules:
    for _name in _module.__all__:
        globals()[_name] = getattr(_module, _name)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PC2 local captcha solver daemon")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--node-id", default=None)
    args = parser.parse_args()
    local_solver_loop(
        api_base_url=str(args.api_base_url),
        cdp_endpoint=str(args.cdp_endpoint),
        poll_seconds=int(args.poll_seconds),
        max_attempts=int(args.max_attempts),
        expected_node_id=str(args.node_id).strip() if args.node_id else None,
    )
