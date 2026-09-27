"""Safe failure receipts and bounded automatic retry of unchanged captures."""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from src.archive_json_io import write_json

InputVersion = tuple[int, int]
_MODEL_STAGES = {"capture", "extraction", "model_result", "risk_facts", "validation"}


def input_version(path: Path) -> InputVersion:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


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
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def ready(self, file_path: str) -> bool:
        path = Path(file_path)
        item_id = path.stem.removeprefix("item-")
        receipt = self._load(item_id)
        try:
            if receipt.get("input_version") != list(input_version(path)):
                return True
            return not receipt.get("exhausted") and time.time() >= float(
                str(receipt.get("retry_at", 0))
            )
        except (OSError, ValueError):
            return True

    def record(
        self, item_id: str, version: InputVersion | None, stage: str, error: Exception
    ) -> None:
        previous = self._load(item_id)
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
                "exhausted": stage in _MODEL_STAGES and attempts >= 2,
                "retry_at": time.time() + (1 if stage in _MODEL_STAGES else 30),
            },
        )

    def clear(self, item_id: str) -> None:
        self.path(item_id).unlink(missing_ok=True)
