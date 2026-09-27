"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tools.manual_review_control_plane_context import *

if TYPE_CHECKING:
    from src.storage.repository import PropertyRepository


def _build_repo(
    db_url: str | None, repository: PropertyRepository | None = None
) -> PropertyRepository:
    if repository is not None:
        return repository
    from src.storage.repository import (
        DatabaseSettings,
        PropertyRepository,
        create_repository_from_env,
    )

    if db_url:
        repo = PropertyRepository(
            DatabaseSettings(
                url=db_url,
                echo=False,
                enable_postgis=True,
                auto_create=True,
                enabled=True,
            )
        )
        repo.initialize()
        return repo
    repo = create_repository_from_env()
    repo.initialize()
    return repo


def _load_receipt_snapshot(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"receipts": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("receipts"), list):
        return {"receipts": []}
    return {"receipts": [dict(item) for item in payload.get("receipts") or [] if isinstance(item, dict)]}


def _load_job_snapshot(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"jobs": [], "queue": [], "running_job_id": None}
    jobs = payload.get("jobs") if isinstance(payload, dict) else []
    queue = payload.get("queue") if isinstance(payload, dict) else []
    running_job_id = payload.get("running_job_id") if isinstance(payload, dict) else None
    return {
        "jobs": [dict(item) for item in jobs if isinstance(item, dict)] if isinstance(jobs, list) else [],
        "queue": [str(item) for item in queue if str(item or "").strip()] if isinstance(queue, list) else [],
        "running_job_id": str(running_job_id).strip() if running_job_id else None,
    }


def _load_operation_snapshot(path: Path) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    items: List[Dict[str, Any]] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items


def _write_json_payload(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _replace_with_retry(temp_path, path)


def _write_jsonl_payload(path: Path, payloads: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    body = "\n".join(json.dumps(payload, ensure_ascii=False) for payload in payloads)
    if body:
        body += "\n"
    temp_path.write_text(body, encoding="utf-8")
    _replace_with_retry(temp_path, path)


def _replace_with_retry(temp_path: Path, path: Path, *, attempts: int = 5, delay_seconds: float = 0.02) -> None:
    last_error: PermissionError | None = None
    for attempt in range(max(attempts, 1)):
        try:
            temp_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt >= max(attempts, 1) - 1:
                break
            time.sleep(delay_seconds)
    if temp_path.exists() and path.exists():
        temp_path.unlink(missing_ok=True)
    if last_error is not None:
        raise last_error


def _backup_repair_log_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_control_plane_backup_repairs.jsonl"


def load_manual_review_control_plane_backup_repairs(data_root: Path) -> list[dict[str, Any]]:
    return _load_operation_snapshot(_backup_repair_log_path(data_root))


def _integrity_history_log_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_control_plane_integrity_history.jsonl"


def load_manual_review_control_plane_integrity_history(data_root: Path) -> list[dict[str, Any]]:
    return _load_operation_snapshot(_integrity_history_log_path(data_root))


__all__ = (
    '_build_repo',
    '_load_receipt_snapshot',
    '_load_job_snapshot',
    '_load_operation_snapshot',
    '_write_json_payload',
    '_write_jsonl_payload',
    '_replace_with_retry',
    '_backup_repair_log_path',
    'load_manual_review_control_plane_backup_repairs',
    '_integrity_history_log_path',
    'load_manual_review_control_plane_integrity_history',
)
