"""Fail closed on unreadable archives and publish JSON or UTF-8 text atomically.

保留「基文件 + journal」的兼容读取和维护入口；生产 facade 仍发布完整快照。
所有读取必须经由 read_records / read_json，否则看不到未合并的 journal。
追加前检查既有 journal，损坏时保留证据并阻止写入，不承诺单次 O(1)。
压缩、追加和 facade 的读改写使用同一事务协议；旧版本写者不受该协议保护。

journal 文件名为 ``<archive>.json.journal``，不会被 ``*.json`` 的 glob 命中。
"""

import json
import logging
import os
import tempfile
from functools import wraps
from pathlib import Path
from typing import cast

from src.archive_transaction import archive_transaction
from src.runtime_json import load_json_file

logger = logging.getLogger(__name__)

JOURNAL_SUFFIX = ".journal"
# 达到该行数即 compact：把 256 次 O(1) 追加合并成 1 次全量写，
# 摊还后单条更新的序列化成本约为原来的 1/256。
COMPACT_LINES = 256
# 小于该字节数不统计行数，避免为了几行 journal 读整个文件。
_COMPACT_MIN_BYTES = 4096
_ID_KEY = "id"


def _serialized(function):
    @wraps(function)
    def call(path, *args, **kwargs):
        with archive_transaction(
            path, read_only=function.__name__ in {"read_records", "read_json"}
        ):
            return function(path, *args, **kwargs)

    return call


def journal_path(path: str | Path) -> Path:
    return Path(str(path) + JOURNAL_SUFFIX)


def _read_base(path: str | Path) -> list[dict[str, object]]:
    try:
        payload = load_json_file(path)
    except FileNotFoundError:
        return []
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) for row in payload
    ):
        raise ValueError("Archive must contain a list of record objects")
    return cast(list[dict[str, object]], payload)


def _read_journal(path: str | Path) -> list[tuple[str, object]]:
    jp = journal_path(path)
    try:
        with open(jp, "r", encoding="utf-8") as handle:
            raw_lines = handle.read().splitlines()
    except FileNotFoundError:
        return []
    ops: list[tuple[str, object]] = []
    for lineno, line in enumerate(raw_lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError as error:
            raise ValueError(f"Corrupt journal line={jp}:{lineno}") from error
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid journal operation={jp}:{lineno}")  # noqa: TRY004 - invalid persisted schema
        if set(entry) == {"u"} and isinstance(entry["u"], dict):
            ops.append(("u", entry["u"]))
        elif set(entry) == {"d"} and isinstance(entry["d"], str):
            ops.append(("d", str(entry["d"])))
        else:
            raise ValueError(f"Invalid journal operation={jp}:{lineno}")
    return ops


def _apply_ops(
    rows: list[dict[str, object]], ops: list[tuple[str, object]]
) -> list[dict[str, object]]:
    result: list[dict[str, object] | None] = [dict(row) for row in rows]
    index: dict[str, int] = {}
    for pos, row in enumerate(result):
        key = str(row.get(_ID_KEY)) if row is not None else "None"
        if key != "None" and key not in index:
            index[key] = pos
    for op, payload in ops:
        if op == "u":
            row = cast(dict[str, object], payload)
            key = str(row.get(_ID_KEY))
            if key == "None":
                result.append(dict(row))
                continue
            pos = index.get(key)
            if pos is None:
                index[key] = len(result)
                result.append(dict(row))
            else:
                result[pos] = dict(row)
        else:
            pos = index.pop(str(payload), None)
            if pos is not None:
                result[pos] = None
    return [row for row in result if row is not None]


@_serialized
def read_records(path: str | Path) -> list[dict[str, object]]:
    rows = _read_base(path)
    ops = _read_journal(path)
    if ops:
        rows = _apply_ops(rows, ops)
    return rows


@_serialized
def read_json(path: str | Path) -> object:
    """journal-aware 通用读取：list[dict] 合并 journal，其它类型原样返回。"""
    payload = load_json_file(path)
    if isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
        ops = _read_journal(path)
        if ops:
            return _apply_ops(cast(list[dict[str, object]], payload), ops)
    return payload


@_serialized
def append_journal(
    path: str | Path,
    *,
    upserts: list[dict[str, object]] | tuple = (),
    deletes: list[str] | tuple = (),
) -> None:
    lines = [
        json.dumps({"u": dict(row)}, ensure_ascii=False, separators=(",", ":"))
        for row in upserts
    ]
    lines.extend(json.dumps({"d": str(item)}, ensure_ascii=False) for item in deletes)
    if not lines:
        return
    jp = journal_path(path)
    _read_journal(path)  # Never append through unexplained corruption.
    payload = "\n".join(lines) + "\n"
    with open(jp, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


@_serialized
def upsert_records(
    path: str | Path, records: object, *, compact_after: int = COMPACT_LINES
) -> None:
    rows = [dict(row) for row in cast(list[dict[str, object]], records)]
    if not rows:
        return
    append_journal(path, upserts=rows)
    _maybe_compact(path, compact_after)


@_serialized
def delete_records(
    path: str | Path, item_ids: object, *, compact_after: int = COMPACT_LINES
) -> None:
    ids = [str(item) for item in cast(list[object], item_ids)]
    if not ids:
        return
    append_journal(path, deletes=ids)
    _maybe_compact(path, compact_after)


def _maybe_compact(path: str | Path, threshold: int) -> None:
    jp = journal_path(path)
    try:
        if os.path.getsize(jp) < _COMPACT_MIN_BYTES:
            return
        with open(jp, "r", encoding="utf-8", errors="replace") as handle:
            lines = sum(1 for _ in handle)
    except OSError:
        return
    if lines < max(int(threshold), 1):
        return
    try:
        compact(path)
    except Exception:
        logger.exception("Compaction failed path=%s", path)


@_serialized
def compact(path: str | Path) -> None:
    # Replaying the same upserts/deletes after a crash is idempotent.
    write_json(path, read_records(path))
    _truncate_journal(path)


def _truncate_journal(path: str | Path) -> None:
    jp = journal_path(path)
    try:
        os.remove(jp)
    except FileNotFoundError:
        return


@_serialized
def write_records(
    path: str | Path,
    records: object,
    *,
    indent: int = 4,
    replay_journal: bool = False,
) -> None:
    rows = cast(list[dict[str, object]], records)
    if replay_journal:
        # 全量重写通常来自粗采集的合并结果；journal 里的条目更新，
        # 必须重放，否则「先 detail 更新、后粗采集整文件写」会丢失更新。
        ops = _read_journal(path)
        if ops:
            rows = _apply_ops(rows, ops)
    if journal_path(path).exists():
        # Drain the OLD generation first. A crash must not replay old operations
        # over a newly published replacement or resurrect its removed records.
        compact(path)
    write_json(path, rows, indent=indent)


def write_json(path: str | Path, value: object, *, indent: int = 4) -> None:
    serialized = json.dumps(value, ensure_ascii=False, indent=indent)
    write_text(path, serialized)


def write_text(path: str | Path, content: str) -> None:
    """Publish UTF-8 evidence without truncating a confirmed archive."""
    target = Path(path)
    # Retain an incomplete/failed temporary snapshot for recovery; never truncate
    # the confirmed archive before writing, flush and fsync all succeed.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix="." + target.name + ".pending-",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    os.replace(temporary, target)
