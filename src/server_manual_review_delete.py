"""Manual-review receipt DELETE transport with explicit runtime dependencies."""

from urllib.parse import urlparse


def delete_receipt(
    handler,
    *,
    endpoints,
    authorize,
    read_body,
    validate,
    data_root,
    repository,
    delete,
    append_operation,
    receipt_context,
    store_path,
    operations_path,
):
    request_path = urlparse(handler.path).path
    if request_path in endpoints:
        if not authorize(handler):
            return
        (accepted, payload) = read_body(handler)
        if not accepted:
            return
        (valid, error_payload) = validate(payload if isinstance(payload, dict) else {})
        if not valid:
            handler.send_error_json(
                status=400,
                code=error_payload["code"],
                message=error_payload["message"],
                details=error_payload.get("details", {}),
            )
            return
        active_data_root = data_root()
        try:
            result = delete(
                store_path(active_data_root),
                action=str(payload["action"]),
                ready_signal=str(payload["ready_signal"]),
                repository=repository(),
            )
            append_operation(
                operations_path(active_data_root),
                operation="deleted",
                receipt={
                    "action": payload["action"],
                    "ready_signal": payload["ready_signal"],
                    "status": "",
                    "payload": {},
                },
                execution_mode="delete",
                deleted=bool(result["deleted"]),
                repository=repository(),
            )
            context = receipt_context(active_data_root)
            handler.send_json(
                {
                    "status": "ok",
                    "deleted": result["deleted"],
                    "receipt_count": result["receipt_count"],
                    "manual_review_receipt_summary": context[
                        "manual_review_receipt_summary"
                    ],
                    "manual_review_receipt_jobs_summary": context[
                        "manual_review_receipt_jobs_summary"
                    ],
                    "manual_review_control_plane_storage": context[
                        "manual_review_control_plane_storage"
                    ],
                    "manual_review_control_plane_backup": context[
                        "manual_review_control_plane_backup"
                    ],
                    "manual_review_control_plane_backup_repairs_summary": context[
                        "manual_review_control_plane_backup_repairs_summary"
                    ],
                    "manual_review_control_plane_integrity": context[
                        "manual_review_control_plane_integrity"
                    ],
                    "manual_review_control_plane_integrity_history_summary": context[
                        "manual_review_control_plane_integrity_history_summary"
                    ],
                    "manual_review_control_plane_stability": context[
                        "manual_review_control_plane_stability"
                    ],
                    "manual_review_control_plane_guidance": context[
                        "manual_review_control_plane_guidance"
                    ],
                    "operator_overview": context["operator_overview"],
                }
            )
        except Exception as e:  # noqa: BLE001 - HTTP boundary reports persistence failures.
            handler.send_error_json(
                status=500,
                code="AVM_MANUAL_REVIEW_RECEIPT_DELETE_FAILED",
                message="manual review receipt 删除失败",
                details={"error": str(e)},
            )
        return
    if request_path.startswith("/api/"):
        handler.send_error_json(
            status=404,
            code="AVM_ENDPOINT_NOT_FOUND",
            message="未找到接口",
            details={"path": request_path},
        )
    else:
        handler.send_response(404)
        handler.end_headers()
