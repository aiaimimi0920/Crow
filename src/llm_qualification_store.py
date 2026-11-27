"""Private cross-process qualification state; no collection database migration."""
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from src.llm_qualification_cases import VERSION
from src.project_data_paths import resolve_project_data_root
from src.project_environment import getenv as project_getenv


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
        with closing(sqlite3.connect(self.path, timeout=5)) as pragma_db:
            try:
                pragma_db.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError as exc:
                # A peer may be using the current journal mode; do not mask I/O errors.
                if getattr(exc, "sqlite_errorcode", None) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise
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
            row = db.execute("SELECT state FROM pools WHERE id=?", (self.key,)).fetchone()
            if row is None:
                raise sqlite3.DatabaseError("Qualification pool state is missing")
            raw_before = row[0]
            state = json.loads(raw_before)
            result = update(state)
            raw_after = json.dumps(state)
            if raw_after != raw_before:
                db.execute("UPDATE pools SET state=? WHERE id=?", (raw_after, self.key))
            return result

    def snapshot(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            row = db.execute("SELECT state FROM pools WHERE id=?", (self.key,)).fetchone()
            if row is None:
                raise sqlite3.DatabaseError("Qualification pool state is missing")
            return json.loads(row[0])
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
        """Bound chat starts across workers sharing this pool (default 4s spacing)."""
        raw_interval = project_getenv("CROW_MODEL_POOL_MIN_INTERVAL_SECONDS")
        try:
            spacing = max(0.0, float(raw_interval)) if raw_interval is not None else 4.0
        except ValueError:
            spacing = 4.0

        def update(state):
            now = time.time()
            if state.get("cooldown_until", 0) > now:
                return None
            delay = max(0, state.get("next_request_at", 0) - now)
            if not delay:
                state["next_request_at"] = now + spacing
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
