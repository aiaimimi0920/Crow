"""Read-only adapters for daily arrays and completed worker final artifacts."""

import json
from hashlib import sha256
from pathlib import Path


def item_identity(row: dict) -> str:
    """Storage item aliases and source item aliases are distinct namespaces."""
    source = row.get("source") if isinstance(row.get("source"), dict) else {}

    def agree(values):
        ids = {str(v).strip() for v in values if v is not None and str(v).strip()}
        if len(ids) > 1:
            raise ValueError("conflicting item ID aliases")
        return next(iter(ids), "")

    storage = agree([row.get("id"), source.get("item_id")])
    platform = agree([row.get("source_item_id"), source.get("source_item_id")])
    return storage or platform


def analysis_item_identity(row: dict) -> str:
    """Namespace-qualified deduplication key, separate from worker directory ID."""
    item_id = item_identity(row)
    if not item_id:
        return ""
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    storage = any(
        v is not None and str(v).strip() for v in (row.get("id"), source.get("item_id"))
    )
    # Preserve unknown platform explicitly; never infer an asset or alias linkage.
    namespace = (
        ["storage"]
        if storage
        else [
            "platform",
            str(
                source.get("source_platform") or row.get("source_platform") or "unknown"
            ),
        ]
    )
    return json.dumps(namespace + [item_id], ensure_ascii=False, separators=(",", ":"))


def processed_final(row: dict) -> bool:
    audit = row.get("audit") if isinstance(row.get("audit"), dict) else {}
    flags = [
        v for v in (row.get("is_processed"), audit.get("is_processed")) if v is not None
    ]
    # Incomplete/conflicting aliases are not certified by the true alias.
    return bool(flags) and all(v is True for v in flags)


def read_source_files(root: Path, layout: str = "daily-archive"):
    if not root.is_dir():
        raise ValueError("source directory does not exist")
    if layout not in ("daily-archive", "worker-final"):
        raise ValueError("unsupported source layout")
    pattern = "final.json" if layout == "worker-final" else "*.json"
    for path in sorted(root.rglob(pattern)):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("source symlink/path escapes selected root")
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
        ):
            raise ValueError(
                "source changed while reading; retry later without mutating collector"
            )
        data = json.loads(raw.decode("utf-8-sig"))
        if layout == "worker-final":
            if not isinstance(data, dict):
                raise TypeError("worker final must be a JSON object")
            if not processed_final(data):
                continue
            item_id = item_identity(data)
            if not path.parent.name.isdecimal() or path.parent.name != item_id:
                raise ValueError("worker item directory and final item ID disagree")
            records = [data]
        else:
            if not isinstance(data, list):
                raise TypeError("daily archive must be a JSON array")
            records = data
        if any(not isinstance(row, dict) for row in records):
            raise TypeError("source records must be objects")
        yield path, records, sha256(raw).digest()
