"""Cooperative worker shutdown and progress heartbeats; never interrupt an item write."""
from contextvars import ContextVar
import json
import logging
import os
from pathlib import Path
import signal
import tempfile
from threading import Event
import time
from typing import Callable

from src.project_environment import getenv as project_getenv

_active: ContextVar["WorkerLifecycle | None"] = ContextVar("worker_lifecycle", default=None)


class WorkerLifecycle:
    def __init__(self, worker_id: str, release: Callable[[str], object], heartbeat_path: Path | None = None):
        self.worker_id, self.release = worker_id, release
        configured = project_getenv("CROW_WORKER_HEARTBEAT_PATH") if heartbeat_path is None else None
        self.path = heartbeat_path or (Path(configured) if configured else None)
        self.stopping = Event()
        self.handlers = {}

    def __enter__(self):
        self.token = _active.set(self)
        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                self.handlers[sig] = signal.signal(sig, self._request_stop)
            self.heartbeat("starting")
        except BaseException:
            self._restore()
            raise
        return self

    def _request_stop(self, _signum, _frame):
        self.stopping.set()

    def __exit__(self, _kind, _error, _traceback):
        try:
            self.release(self.worker_id)
        except Exception:
            logging.getLogger(__name__).exception("Worker lease release failed; persisted leases will expire")
        finally:
            try:
                self.heartbeat("stopped")
            finally:
                self._restore()

    def _restore(self):
        for sig, handler in self.handlers.items():
            signal.signal(sig, handler)
        _active.reset(self.token)

    def heartbeat(self, stage: str) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump({"worker_id": self.worker_id, "pid": os.getpid(), "stage": stage,
                           "updated_at_epoch": time.time()}, output)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def checkpoint(self, stage: str) -> bool:
        if self.stopping.is_set():
            return False
        self.heartbeat(stage)
        return True

    def wait(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0, seconds)
        while not self.stopping.is_set():
            self.heartbeat("waiting")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.stopping.wait(min(remaining, 30)):
                return


def checkpoint(stage: str) -> bool:
    lifecycle = _active.get()
    return lifecycle.checkpoint(stage) if lifecycle else True


def wait(seconds: float) -> None:
    lifecycle = _active.get()
    if lifecycle:
        lifecycle.wait(seconds)
    else:
        time.sleep(seconds)
