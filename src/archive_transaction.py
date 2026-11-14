"""Reentrant archive transactions shared by cooperating local processes.

Lock files are permanent synchronization objects, not disposable journals.
All writers of an archive must use this protocol; old binaries must be stopped
before migration or rollback. Network filesystem locking is not assumed.
"""

import os
import threading
from contextlib import contextmanager
from pathlib import Path

ARCHIVE_LOCK = threading.RLock()
_held = threading.local()


@contextmanager
def archive_transaction(path, *, read_only=False):
    key = os.path.normcase(os.path.abspath(path))
    with ARCHIVE_LOCK:
        held = getattr(_held, "paths", set())
        if key in held:
            yield
            return
        lock_path = Path(key + ".lock")
        if read_only and not lock_path.exists():
            # Legacy read-only inspection must not create runtime artifacts.
            yield
            return
        with lock_path.open("a+b") as handle:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

                def unlock():
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

                def unlock():
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

            _held.paths = held | {key}
            try:
                yield
            finally:
                _held.paths = held
                unlock()
