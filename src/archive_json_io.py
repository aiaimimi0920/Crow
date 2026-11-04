"""Fail closed on unreadable archives and publish JSON or UTF-8 text atomically.

归档写入采用「基文件 + 追加式 journal」：

* 单条 upsert / delete 只追加一行 JSONL，写成本 O(1)，不再整文件
  read-modify-write（原实现每更新一条记录都要 dumps 整个日分区再 fsync）；
* **所有读取必须经由 read_records / read_json**，否则看不到尚未合并的 journal；
* journal 行数达到阈值时自动 compact：把 journal 合并回基文件并截断。

journal 文件名为 ``<archive>.json.journal``，不会被 ``*.json`` 的 glob 命中。
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import cast

from src.runtime_json import load_json_file

logger = logging.getLogger(__name__)

JOURNAL_SUFFIX = ".journal"
# 达到该行数即 compact：把 256 次 O(1) 追加合并成 1 次全量写，
# 摊还后单条更新的序列化成本约为原来的 1/256。
COMPACT_LINES = 256
# 小于该字节数不统计行数，避免为了几行 journal 读整个文件。
_COMPACT_MIN_BYTES = 4096
_ID_KEY = "id"


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
        with open(jp, "r", encoding="utf-8", errors="replace") as handle:
            raw_lines = handle.read().splitlines()
    except FileNotFoundError:
        return []
    except OSError:
        logger.exception("Journal unreadable, ignoring path=%s", jp)
        return []
    ops: list[tuple[str, object]] = []
    for lineno, line in enumerate(raw_lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            # 崩溃可能留下半行：跳过该行，而不是让整个归档不可读
            logger.warning("Skip corrupt journal line=%s:%s", jp, lineno)
            continue
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("u"), dict):
            ops.append(("u", entry["u"]))
        elif "d" in entry:
            ops.append(("d", str(entry["d"])))
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


def read_records(path: str | Path) -> list[dict[str, object]]:
    rows = _read_base(path)
    ops = _read_journal(path)
    if ops:
        rows = _apply_ops(rows, ops)
    return rows


def read_json(path: str | Path) -> object:
    """journal-aware 通用读取：list[dict] 合并 journal，其它类型原样返回。"""
    payload = load_json_file(path)
    if isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
        ops = _read_journal(path)
        if ops:
            return _apply_ops(cast(list[dict[str, object]], payload), ops)
    return payload


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
    payload = "\n".join(lines) + "\n"
    with open(jp, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def upsert_records(
    path: str | Path, records: object, *, compact_after: int = COMPACT_LINES
) -> None:
    rows = [dict(row) for row in cast(list[dict[str, object]], records)]
    if not rows:
        return
    append_journal(path, upserts=rows)
    _maybe_compact(path, compact_after)


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
    except Exception:  # noqa: BLE001 - journal 已落盘，压缩失败不影响正确性
        logger.exception("Compaction failed path=%s", path)


def compact(path: str | Path) -> None:
    write_records(path, read_records(path), replay_journal=False)


def _truncate_journal(path: str | Path) -> None:
    jp = journal_path(path)
    try:
        os.remove(jp)
    except FileNotFoundError:
        return
    except OSError:
        logger.exception("Journal truncate failed path=%s", jp)


def write_records(
    path: str | Path,
    records: object,
    *,
    indent: int = 4,
    replay_journal: bool = True,
) -> None:
    rows = cast(list[dict[str, object]], records)
    if replay_journal:
        # 全量重写通常来自粗采集的合并结果；journal 里的条目更新，
        # 必须重放，否则「先 detail 更新、后粗采集整文件写」会丢失更新。
        ops = _read_journal(path)
        if ops:
            rows = _apply_ops(rows, ops)
    write_json(path, rows, indent=indent)
    _truncate_journal(path)


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
