"""Read the scheduled backup receipt; only the host CLI can also check the dump."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

MAX_AGE_HOURS = 12.0


def read_receipt(data_root, *, max_age=MAX_AGE_HOURS, archive_dir=None):
    marker = Path(data_root) / "postgres-backup-status.json"
    try:
        raw = json.loads(marker.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"ok": False, "reason": "invalid_backup_status_json"}

    if not isinstance(raw, dict) or raw.get("ok") is not True:
        return {"ok": False, "reason": "invalid_backup_receipt"}
    name = raw.get("latest_backup_file")
    size, entries = raw.get("size_bytes"), raw.get("toc_entries")
    if (not isinstance(name, str) or not re.fullmatch(r"fapaifang-[0-9]{8}-[0-9]{6}\.dump", name)
            or type(size) is not int or size < 1024 or type(entries) is not int or entries < 5):
        return {"ok": False, "reason": "invalid_backup_receipt"}
    try:
        stamp = datetime.fromisoformat(raw["generated_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return {"ok": False, "reason": "invalid_backup_timestamp"}

    result = {key: raw[key] for key in ("generated_at", "latest_backup_file", "size_bytes", "toc_entries")}
    for key in ("retained_backups", "pruned_backups", "keep_recent_days", "keep_daily_days"):
        if type(raw.get(key)) is int:
            result[key] = raw[key]
    result.update(ok=True, age_hours=round(age, 2), max_age_hours=max_age)
    if not math.isfinite(max_age) or max_age <= 0:
        return {"ok": False, "reason": "invalid_max_age"}
    if age < 0 or age > max_age:
        result.update(ok=False, reason="future_backup_timestamp" if age < 0 else "stale_backup")
    elif archive_dir is not None:
        dump = Path(archive_dir) / name
        try:
            if dump.is_symlink() or not dump.is_file() or dump.stat().st_size != size:
                result.update(ok=False, reason="backup_file_mismatch")
        except OSError:
            result.update(ok=False, reason="backup_file_unavailable")
    return result


if __name__ == "__main__":
    import sys

    root = Path(sys.argv[1])
    receipt = read_receipt(root / "datas", archive_dir=root / "backups/postgres/scheduled", max_age=float(sys.argv[2]))
    receipt = receipt or {"ok": False, "reason": "missing_backup_receipt"}
    print(json.dumps(receipt))
    sys.exit(0 if receipt["ok"] else 1)
