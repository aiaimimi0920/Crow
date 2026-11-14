"""Safe failure receipts and bounded automatic retry of unchanged captures."""

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

from src.archive_json_io import write_json

InputVersion = tuple[int, int]
_MODEL_STAGES = {"capture", "extraction", "model_result", "risk_facts", "validation"}

_MAX_ATTEMPTS_MODEL = 5  # 模型阶段原为 2 次，对瞬断/风控页几乎没有容错
_BACKOFF_BASE_MODEL = 5.0  # 原实现固定 1s，等同于无退避
_BACKOFF_BASE_DEFAULT = 30.0
_BACKOFF_MAX = 300.0  # 与 auth_cookie_snapshot_retry 上限对齐
logger = logging.getLogger(__name__)


def _retry_delay_seconds(stage: str, attempts: int) -> float:
    """指数退避：base * 2**(attempts-1)，上限 _BACKOFF_MAX。"""
    base = _BACKOFF_BASE_MODEL if stage in _MODEL_STAGES else _BACKOFF_BASE_DEFAULT
    return min(base * (2 ** min(10, max(0, int(attempts) - 1))), _BACKOFF_MAX)


def input_version(path: Path) -> InputVersion:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def content_unchanged(path: Path, content: str) -> bool:
    """相同证据不替换文件，保留 mtime 身份和已有退避预算。"""
    try:
        return path.read_bytes() == content.encode("utf-8")
    except (OSError, UnicodeEncodeError):
        return False


def read_capture(path: Path) -> tuple[str, InputVersion]:
    with path.open(encoding="utf-8") as stream:
        stat = os.fstat(stream.fileno())
        return stream.read(), (stat.st_size, stat.st_mtime_ns)


@dataclass(frozen=True)
class DetailFailures:
    data_root: Path

    def path(self, item_id: str) -> Path:
        return self.data_root / "failed" / f"item-{item_id}.html.failed"

    def _load(self, item_id: str) -> dict[str, object]:
        try:
            value = json.loads(self.path(item_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(value, dict):
            raise ValueError("Invalid detail failure receipt")  # noqa: TRY004 - invalid persisted schema
        version = value.get("input_version")
        attempts = value.get("attempts")
        retry_at = value.get("retry_at")
        if not (
            isinstance(version, list)
            and len(version) in (0, 2)
            and all(type(part) is int and part >= 0 for part in version)
            and type(attempts) is int
            and attempts > 0
            and type(value.get("exhausted")) is bool
            and type(retry_at) in (int, float)
            and math.isfinite(retry_at)
            and retry_at >= 0
        ):
            raise ValueError("Invalid detail failure receipt fields")
        return value

    def ready(self, file_path: str) -> bool:
        path = Path(file_path)
        item_id = path.stem.removeprefix("item-")
        try:
            receipt = self._load(item_id)
            if not receipt:
                return True
            if receipt.get("input_version") != list(input_version(path)):
                return True
            return not receipt.get("exhausted") and time.time() >= float(
                str(receipt.get("retry_at", 0))
            )
        except (OSError, ValueError):
            logger.exception(
                "Detail retry blocked by unreadable evidence item=%s", item_id
            )
            return False

    def record(
        self, item_id: str, version: InputVersion | None, stage: str, error: Exception
    ) -> None:
        try:
            previous = self._load(item_id)
        except (OSError, ValueError):
            logger.exception(
                "Detail failure receipt preserved for repair item=%s", item_id
            )
            return
        previous_attempts = previous.get("attempts", 0)
        attempts = (
            previous_attempts
            if previous.get("input_version") == list(version or ())
            and isinstance(previous_attempts, int)
            else 0
        ) + 1
        self.path(item_id).parent.mkdir(parents=True, exist_ok=True)
        write_json(
            self.path(item_id),
            {
                "stage": stage,
                "code": "COLLECTION_DETAIL_" + stage.upper() + "_FAILED",
                "error_type": type(error).__name__,
                "input_version": list(version or ()),
                "attempts": attempts,
                "exhausted": stage in _MODEL_STAGES and attempts >= _MAX_ATTEMPTS_MODEL,
                "retry_at": time.time() + _retry_delay_seconds(stage, attempts),
            },
        )

    def clear(self, item_id: str) -> None:
        self.path(item_id).unlink(missing_ok=True)
