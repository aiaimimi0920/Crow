"""Authenticated entry into the existing PC1 -> NAS -> PC2 cookie handoff."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .server_request_guard import _read_limited_body

if TYPE_CHECKING:
    from .nas_auth_recovery import NasAuthRecoveryCoordinator
    from .runtime_state import RuntimeState


def _server_desktop_auth_request(
    handler: Any,
    *,
    authorize_recovery: Callable[[Any], tuple[bool, str]],
    solver_scope_status: Callable[[str], dict[str, Any]],
    solver_status: Callable[[], dict[str, Any]],
    set_pause_state: Callable[..., None],
    nas_auth_recovery: NasAuthRecoveryCoordinator,
    runtime: RuntimeState,
) -> None:
    from src.collection.adapters.taobao_auth_target import (
        auth_target,
        matches_challenge_target,
    )

    authorized, _error = authorize_recovery(handler.headers)
    if not authorized:
        handler.send_error_json(
            status=403,
            code="AUTH_RECOVERY_FORBIDDEN",
            message="认证恢复凭据不可用",
            details={},
        )
        return
    try:
        body = _read_limited_body(handler, max_bytes=4096, min_bytes=2)
        payload = json.loads(body)
        if not isinstance(payload, dict) or set(payload) not in (
            {"request_id", "challenge_id"},
            {"request_id", "challenge_id", "scope", "target_url", "protocol_version"},
        ):
            raise ValueError("Invalid request fields")
        scope = payload.get("scope", "")
        if "scope" in payload and scope not in {"seed", "detail"}:
            raise ValueError("Invalid authentication scope")
        target_url = ""
        if scope:
            if payload.get("protocol_version") != 2:
                raise ValueError("Invalid stage protocol")
            target_url = auth_target(scope, payload["target_url"])
            if not nas_auth_recovery.snapshot().get("pc2_stage_auth_ready"):
                handler.send_error_json(
                    status=412,
                    code="AUTH_PC2_UPGRADE_REQUIRED",
                    message="PC2 分阶段认证组件尚未就绪",
                    details={},
                )
                return
        expected = payload["challenge_id"]
        if not isinstance(expected, str) or len(expected) > 256:
            raise ValueError("Invalid challenge identity")
        status = solver_scope_status(scope) if scope else solver_status()
        current = str(status.get("challenge_id") or "")
        if expected != current or (
            scope and not matches_challenge_target(scope, target_url, status)
        ):
            handler.send_error_json(
                status=409,
                code="AUTH_CHALLENGE_CHANGED",
                message="挑战已变化，请重新打开挑战页面",
                details={},
            )
            return
        result = nas_auth_recovery.request_manual(
            payload["request_id"],
            scope=scope,
            challenge_id=expected,
            target_url=target_url,
        )
        if not result.get("ok"):
            handler.send_error_json(
                status=423 if result.get("busy") else 409,
                code="AUTH_RECOVERY_REJECTED",
                message="无法建立认证恢复任务",
                details={},
            )
            return
        recovery = result.get("recovery") or {}
        if recovery.get("manual_request_id") and recovery.get("status") in {
            "requested",
            "pc1_claimed",
        }:
            if scope:
                if runtime.control.snapshot().reason != "operator":
                    set_pause_state(True, "manual_required", scope=scope)
                handler.send_json(result)
                return
            # This explicit completion supersedes an earlier desktop/operator pause;
            # a new operator pause during recovery still blocks automatic resume.
            runtime.solver.record_outcome("manual_required", "manual_required")
            set_pause_state(True, "manual_required")
        handler.send_json(result)
    except (ValueError, TypeError, UnicodeError):
        handler.send_error_json(
            status=400,
            code="AUTH_RECOVERY_INVALID",
            message="认证恢复请求无效",
            details={},
        )
    except OSError:
        handler.send_error_json(
            status=503,
            code="AUTH_RECOVERY_UNAVAILABLE",
            message="认证恢复状态暂不可用",
            details={},
        )


__all__ = ["_server_desktop_auth_request"]
