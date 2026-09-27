"""Immutable manual snapshots: never overwrite the running collector's cookies."""

import hashlib
import json
import os
from contextlib import contextmanager

from src.auth_snapshot_contract import RecoveryError, snapshot_path


def validate_snapshot(raw):
    if not 0 < len(raw) <= 5 * 1024 * 1024:
        raise RecoveryError("invalid_snapshot")
    try:
        cookies = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise RecoveryError("invalid_snapshot") from error
    if not isinstance(cookies, list) or not cookies:
        raise RecoveryError("invalid_snapshot")
    for cookie in cookies:
        if not isinstance(cookie, dict) or not all(
            isinstance(cookie.get(key), str) for key in ("name", "value", "domain")
        ):
            raise RecoveryError("invalid_snapshot")
        if not cookie["name"] or not cookie["domain"]:
            raise RecoveryError("invalid_snapshot")
    return len(cookies), hashlib.sha256(raw).hexdigest()


def publish_snapshot(base, recovery_id, raw):
    count, digest = validate_snapshot(raw)
    destination = snapshot_path(base, recovery_id, digest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if destination.read_bytes() != raw:
            raise RecoveryError("invalid_snapshot")
    else:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return count, digest


@contextmanager
def completion_lock(base):
    """OS lock releases on process exit, including a crashed desktop instance."""
    base.parent.mkdir(parents=True, exist_ok=True)
    lock_path = base.parent / ".desktop-auth.lock"
    with lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RecoveryError("handoff_busy") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
