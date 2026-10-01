"""Private cross-process qualification state; no collection database migration."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from src.project_environment import getenv as project_getenv
from src.llm_qualification_cases import VERSION
from src.project_data_paths import resolve_project_data_root


class QualificationStore:
    @staticmethod
    def resolve_path(path=None):
        explicit = path or project_getenv("CROW_ANALYSIS_MODEL_POOL_PATH")
        if explicit:
            return Path(explicit).resolve()
        return resolve_project_data_root(Path(__file__).resolve().parents[1]) / "model-pool" / "pool.sqlite3"

    @staticmethod
    def identity(config):
        identity = json.dumps([config["base_url"], config["api_key"], VERSION,
                               config.get("reasoning_effort") or None, config.get("timeout")])
        return hashlib.sha256(identity.encode()).hexdigest()

    def __init__(self, config, path=None):
        self.path = self.resolve_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.key = self.identity(config)
        self.owner = uuid.uuid4().hex
        # A reused owner's lease must never be acquired by two local scans.
        self.scan_lock = threading.Lock()
        with self._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS pools (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO pools VALUES (?, ?)", (self.key, json.dumps({
                "models": {}, "cursor": 0, "lease": "", "lease_until": 0, "next_scan": 0,
                "scan_complete": False, "route_cursor": 0,
            })))
        if os.name != "nt":
            self.path.chmod(0o600)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def change(self, update):
        with self._connection() as db:
            state = json.loads(db.execute("SELECT state FROM pools WHERE id=?", (self.key,)).fetchone()[0])
            result = update(state)
            db.execute("UPDATE pools SET state=? WHERE id=?", (json.dumps(state), self.key))
            return result

    def snapshot(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            return json.loads(db.execute("SELECT state FROM pools WHERE id=?", (self.key,)).fetchone()[0])
        finally:
            db.close()

    def claim(self, now=None):
        now = time.time() if now is None else now

        def update(state):
            if state["lease_until"] > now or state["next_scan"] > now:
                return False
            state.update(lease=self.owner, lease_until=now + 600)
            return True

        return self.change(update)

    def record(self, model, result):
        def update(state):
            if state["lease"] != self.owner or state["lease_until"] <= time.time():
                raise RuntimeError("Model qualification lease expired")
            state["models"][model] = result
        self.change(update)

    def finish(self, cursor, complete=False):
        def update(state):
            if state["lease"] == self.owner:
                state.update(lease="", lease_until=0, next_scan=max(state["next_scan"], time.time() + 120),
                              cursor=cursor, scan_complete=complete)
        self.change(update)

    def reserve_request_slot(self):
        """At most 15 chat starts per minute across workers sharing this pool."""
        def update(state):
            now = time.time()
            if state.get("cooldown_until", 0) > now:
                return None
            delay = max(0, state.get("next_request_at", 0) - now)
            if not delay:
                state["next_request_at"] = now + 4
            return delay
        return self.change(update)

    def defer_scan(self, seconds):
        """Delay discovery without blocking qualified business requests."""
        def update(state):
            state["next_scan"] = max(state["next_scan"], time.time() + max(60, seconds))
        self.change(update)

    def cool_down(self, seconds):
        def update(state):
            until = max(state.get("cooldown_until", 0), time.time() + max(60, seconds))
            state.update(cooldown_until=until, next_scan=max(state["next_scan"], until),
                         next_request_at=max(state.get("next_request_at", 0), until))
        self.change(update)

    def route_order(self, models):
        if not models:
            return []
        def update(state):
            cursor = state.get("route_cursor", 0) % len(models)
            state["route_cursor"] = cursor + 1
            return models[cursor:] + models[:cursor]
        return self.change(update)

    def disable(self, model):
        def update(state):
            if model in state["models"]:
                state["models"][model]["blocked_until"] = time.time() + 900
        self.change(update)
