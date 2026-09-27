"""Authorized recovery state and digest-checked snapshot HTTP reads."""

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol, cast

from .auth_recovery_codes import SNAPSHOT_AVAILABLE_STATUSES
from .auth_snapshot_contract import snapshot_path as manual_snapshot_path

SNAPSHOT_MAX_BYTES = 5 * 1024 * 1024


class RecoveryReadHandler(Protocol):
    headers: object

    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self,
        *,
        status: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None: ...


class RecoveryState(Protocol):
    def snapshot(self) -> object: ...


class RecoveryReadHost(Protocol):
    NAS_AUTH_RECOVERY: RecoveryState

    def _nas_auth_recovery_authorized(self, headers: object) -> tuple[bool, object]: ...
    def _resolve_auth_cookie_snapshot_path(
        self, payload: dict[str, object]
    ) -> str | Path: ...


GetHandler = Callable[[RecoveryReadHandler, object, str, dict[str, list[str]]], None]


@dataclass(frozen=True)
class RecoveryReadHandlers:
    _get_auth_recovery: GetHandler
    _get_auth_recovery_snapshot: GetHandler
    __all__: ClassVar[list[str]] = ["_get_auth_recovery", "_get_auth_recovery_snapshot"]


def bind_recovery_reads(host: RecoveryReadHost) -> RecoveryReadHandlers:
    def _get_auth_recovery(
        handler: RecoveryReadHandler,
        parsed: object,
        request_path: str,
        query: dict[str, list[str]],
    ) -> None:
        authorized, auth_error = host._nas_auth_recovery_authorized(handler.headers)
        if not authorized:
            handler.send_error_json(
                status=403,
                code="COLLECTION_AUTH_RECOVERY_FORBIDDEN",
                message="跨设备认证恢复凭据无效",
                details={"error": auth_error},
            )
            return
        handler.send_json(
            {"ok": True, "auth_recovery": host.NAS_AUTH_RECOVERY.snapshot()}
        )

    def _get_auth_recovery_snapshot(
        handler: RecoveryReadHandler,
        parsed: object,
        request_path: str,
        query: dict[str, list[str]],
    ) -> None:
        authorized, auth_error = host._nas_auth_recovery_authorized(handler.headers)
        if not authorized:
            handler.send_error_json(
                status=403,
                code="COLLECTION_AUTH_RECOVERY_FORBIDDEN",
                message="跨设备认证恢复凭据无效",
                details={"error": auth_error},
            )
            return
        recovery_id = str((query.get("recovery_id") or [""])[0] or "").strip()
        recovery_state = host.NAS_AUTH_RECOVERY.snapshot()
        active = (
            recovery_state.get("active") if isinstance(recovery_state, dict) else None
        )
        if (
            not recovery_id
            or not isinstance(active, dict)
            or str(active.get("recovery_id") or "") != recovery_id
        ):
            handler.send_error_json(
                status=409,
                code="COLLECTION_AUTH_RECOVERY_NOT_ACTIVE",
                message="认证恢复任务已变化，请重新拉取状态",
            )
            return
        status = str(active.get("status") or "")
        snapshot_value = active.get("snapshot")
        snapshot = (
            cast(dict[str, object], snapshot_value)
            if isinstance(snapshot_value, dict)
            else {}
        )
        expected_sha256 = str(snapshot.get("sha256") or "").strip().lower()
        if status not in SNAPSHOT_AVAILABLE_STATUSES or not expected_sha256:
            handler.send_error_json(
                status=409,
                code="COLLECTION_AUTH_RECOVERY_SNAPSHOT_NOT_READY",
                message="认证快照尚未就绪",
            )
            return
        snapshot_path = Path(
            host._resolve_auth_cookie_snapshot_path({"node_id": "pc2"})
        )
        if active.get("manual_request_id"):
            snapshot_path = manual_snapshot_path(
                snapshot_path, recovery_id, expected_sha256
            )
        try:
            with snapshot_path.open("rb") as stream:
                raw_snapshot = stream.read(SNAPSHOT_MAX_BYTES + 1)
        except OSError:
            handler.send_error_json(
                status=404,
                code="COLLECTION_AUTH_RECOVERY_SNAPSHOT_MISSING",
                message="NAS 认证快照文件不存在",
            )
            return
        if not raw_snapshot or len(raw_snapshot) > SNAPSHOT_MAX_BYTES:
            handler.send_error_json(
                status=409,
                code="COLLECTION_AUTH_RECOVERY_SNAPSHOT_INVALID",
                message="NAS 认证快照大小无效",
            )
            return
        actual_sha256 = hashlib.sha256(raw_snapshot).hexdigest()
        if actual_sha256 != expected_sha256:
            handler.send_error_json(
                status=409,
                code="COLLECTION_AUTH_RECOVERY_SNAPSHOT_CHANGED",
                message="NAS 认证快照摘要已变化，请等待 PC1 重新发布",
            )
            return
        handler.send_json(
            {
                "ok": True,
                "recovery_id": recovery_id,
                "sha256": actual_sha256,
                "encoding": "base64",
                "snapshot": base64.b64encode(raw_snapshot).decode("ascii"),
            }
        )

    return RecoveryReadHandlers(_get_auth_recovery, _get_auth_recovery_snapshot)
