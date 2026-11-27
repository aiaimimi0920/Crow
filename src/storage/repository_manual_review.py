from __future__ import annotations

from typing import Any, Dict, Sequence
from uuid import uuid4

from sqlalchemy import select

from .models import (
    ManualReviewReceipt,
    ManualReviewReceiptOperation,
)
from .repository_context import (
    _manual_review_payload_fingerprint,
    _parse_dt,
    _utc_now,
)
from .repository_manual_review_jobs import RepositoryManualReviewJobsMixin


class RepositoryManualReviewMixin(RepositoryManualReviewJobsMixin):
    def _manual_review_receipt_payload_from_row(
        self, row: ManualReviewReceipt
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "action": row.action,
            "ready_signal": row.ready_signal,
            "status": row.status,
            "payload": dict(row.payload or {}),
            "updated_at": self._fmt_dt(
                row.receipt_updated_at or row.updated_at or row.created_at
            ),
        }
        if row.source:
            payload["source"] = row.source
        if row.resolution_notes:
            payload["resolution_notes"] = row.resolution_notes
        return payload

    def list_manual_review_receipts(self) -> Dict[str, list[Dict[str, Any]]]:
        if not self.enabled:
            return {"receipts": []}
        self.initialize()
        with self.session_factory() as session:
            rows = session.execute(
                select(ManualReviewReceipt).order_by(
                    ManualReviewReceipt.action.asc(),
                    ManualReviewReceipt.ready_signal.asc(),
                )
            ).scalars()
            return {
                "receipts": [
                    self._manual_review_receipt_payload_from_row(row) for row in rows
                ]
            }

    def upsert_manual_review_receipt(self, receipt: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "operation": "created",
                "receipt": dict(receipt),
                "receipt_count": 0,
            }
        self.initialize()
        action = str(receipt.get("action") or "").strip()
        ready_signal = str(receipt.get("ready_signal") or "").strip()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(
                ManualReviewReceipt, {"action": action, "ready_signal": ready_signal}
            )
            operation = "updated" if row is not None else "created"
            if row is None:
                row = ManualReviewReceipt(
                    action=action,
                    ready_signal=ready_signal,
                    status=str(receipt.get("status") or "").strip(),
                )
            row.status = str(receipt.get("status") or "").strip()
            row.payload = dict(receipt.get("payload") or {})
            row.source = str(receipt.get("source") or "").strip() or None
            row.resolution_notes = (
                str(receipt.get("resolution_notes") or "").strip() or None
            )
            row.receipt_updated_at = now
            session.add(row)

        snapshot = self.list_manual_review_receipts()
        persisted = next(
            (
                dict(item)
                for item in snapshot.get("receipts") or []
                if item.get("action") == action
                and item.get("ready_signal") == ready_signal
            ),
            {
                "action": action,
                "ready_signal": ready_signal,
                "status": str(receipt.get("status") or "").strip(),
                "payload": dict(receipt.get("payload") or {}),
                "updated_at": self._fmt_dt(now),
            },
        )
        return {
            "operation": operation,
            "receipt": persisted,
            "receipt_count": len(snapshot.get("receipts") or []),
        }

    def import_manual_review_receipt_snapshot(self, snapshot: Dict[str, Any]) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        receipts = snapshot.get("receipts") if isinstance(snapshot, dict) else []
        if not isinstance(receipts, list):
            return 0
        imported = 0
        with self.session_factory.begin() as session:
            for item in receipts:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action") or "").strip()
                ready_signal = str(item.get("ready_signal") or "").strip()
                if not action or not ready_signal:
                    continue
                row = session.get(
                    ManualReviewReceipt,
                    {"action": action, "ready_signal": ready_signal},
                )
                if row is None:
                    row = ManualReviewReceipt(
                        action=action,
                        ready_signal=ready_signal,
                        status=str(item.get("status") or "").strip(),
                    )
                row.status = str(item.get("status") or "").strip()
                row.payload = dict(item.get("payload") or {})
                row.source = str(item.get("source") or "").strip() or None
                row.resolution_notes = (
                    str(item.get("resolution_notes") or "").strip() or None
                )
                row.receipt_updated_at = _parse_dt(item.get("updated_at")) or _utc_now()
                session.add(row)
                imported += 1
        return imported

    def delete_manual_review_receipt(
        self, action: str, ready_signal: str
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"deleted": False, "receipt_count": 0}
        self.initialize()
        action_key = str(action or "").strip()
        ready_signal_key = str(ready_signal or "").strip()
        deleted = False
        with self.session_factory.begin() as session:
            row = session.get(
                ManualReviewReceipt,
                {"action": action_key, "ready_signal": ready_signal_key},
            )
            if row is not None:
                session.delete(row)
                deleted = True
        receipt_count = len(self.list_manual_review_receipts().get("receipts") or [])
        return {"deleted": deleted, "receipt_count": receipt_count}

    def _manual_review_receipt_operation_payload_from_row(
        self, row: ManualReviewReceiptOperation
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "operation_id": row.operation_id,
            "operation": row.operation,
            "action": row.action,
            "ready_signal": row.ready_signal,
            "status": row.status or "",
            "payload_fingerprint": row.payload_fingerprint,
            "source": row.source,
            "execution_mode": row.execution_mode,
            "requested_at": self._fmt_dt(row.requested_at),
        }
        if row.maintenance_job_id:
            payload["maintenance_job_id"] = row.maintenance_job_id
        if row.deleted is not None:
            payload["deleted"] = bool(row.deleted)
        if row.resolution_notes:
            payload["resolution_notes"] = row.resolution_notes
        return payload

    def append_manual_review_receipt_operation(
        self,
        *,
        operation: str,
        receipt: Dict[str, Any] | None,
        execution_mode: str,
        maintenance_job_id: str | None = None,
        deleted: bool | None = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        self.initialize()
        receipt = dict(receipt or {})
        now = _utc_now()
        row = ManualReviewReceiptOperation(
            operation_id=str(uuid4()),
            operation=str(operation or "").strip(),
            action=str(receipt.get("action") or "").strip(),
            ready_signal=str(receipt.get("ready_signal") or "").strip(),
            status=str(receipt.get("status") or "").strip(),
            payload_fingerprint=_manual_review_payload_fingerprint(
                receipt.get("payload")
            ),
            source=str(receipt.get("source") or "").strip() or None,
            execution_mode=str(execution_mode or "").strip() or "sync",
            maintenance_job_id=str(maintenance_job_id or "").strip() or None,
            deleted=deleted,
            resolution_notes=str(receipt.get("resolution_notes") or "").strip() or None,
            requested_at=now,
        )
        with self.session_factory.begin() as session:
            session.add(row)
        return self._manual_review_receipt_operation_payload_from_row(row)

    def import_manual_review_receipt_operations(
        self, operations: Sequence[Dict[str, Any]]
    ) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        imported = 0
        with self.session_factory.begin() as session:
            for item in operations:
                if not isinstance(item, dict):
                    continue
                operation_id = str(item.get("operation_id") or "").strip()
                action = str(item.get("action") or "").strip()
                ready_signal = str(item.get("ready_signal") or "").strip()
                if not operation_id or not action or not ready_signal:
                    continue
                row = session.execute(
                    select(ManualReviewReceiptOperation).where(
                        ManualReviewReceiptOperation.operation_id == operation_id
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = ManualReviewReceiptOperation(operation_id=operation_id)
                row.operation = str(item.get("operation") or "").strip()
                row.action = action
                row.ready_signal = ready_signal
                row.status = str(item.get("status") or "").strip()
                row.payload_fingerprint = (
                    str(item.get("payload_fingerprint") or "").strip()
                    or _manual_review_payload_fingerprint({})
                )
                row.source = str(item.get("source") or "").strip() or None
                row.execution_mode = (
                    str(item.get("execution_mode") or "").strip() or "sync"
                )
                row.maintenance_job_id = (
                    str(item.get("maintenance_job_id") or "").strip() or None
                )
                row.deleted = (
                    item.get("deleted") if item.get("deleted") is not None else None
                )
                row.resolution_notes = (
                    str(item.get("resolution_notes") or "").strip() or None
                )
                row.requested_at = _parse_dt(item.get("requested_at")) or _utc_now()
                session.add(row)
                imported += 1
        return imported

    def list_manual_review_receipt_operations(
        self,
        *,
        action: str | None = None,
        ready_signal: str | None = None,
        limit: int | None = None,
    ) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        if limit is not None and limit == 0:
            return []
        self.initialize()
        with self.session_factory() as session:
            stmt = select(ManualReviewReceiptOperation)
            if action:
                stmt = stmt.where(
                    ManualReviewReceiptOperation.action == str(action).strip()
                )
            if ready_signal:
                stmt = stmt.where(
                    ManualReviewReceiptOperation.ready_signal
                    == str(ready_signal).strip()
                )
            if limit is not None and limit > 0:
                stmt = stmt.order_by(
                    ManualReviewReceiptOperation.requested_at.desc(),
                    ManualReviewReceiptOperation.id.desc(),
                ).limit(limit)
                rows = list(reversed(list(session.execute(stmt).scalars())))
            else:
                stmt = stmt.order_by(
                    ManualReviewReceiptOperation.requested_at.asc(),
                    ManualReviewReceiptOperation.id.asc(),
                )
                rows = list(session.execute(stmt).scalars())
        return [
            self._manual_review_receipt_operation_payload_from_row(row) for row in rows
        ]
