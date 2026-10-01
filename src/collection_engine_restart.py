"""Durable, single-target PC2 restart mailbox. No shell execution on the NAS."""

from __future__ import annotations

import hmac
import re
import secrets
import sqlite3
import time
from pathlib import Path

from src.credential_header_aliases import credential_header
from src.project_environment import getenv as project_getenv

from .project_data_paths import resolve_project_data_root

PREFIX = "/api/collection/control/restart"
ROUTES = {PREFIX, f"{PREFIX}/poll", f"{PREFIX}/result"}
ACTIVE = ("requested", "restarting")


class RestartError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def token(role: str) -> str:
    path = project_getenv(f"CROW_ENGINE_{role.upper()}_TOKEN_FILE", "").strip()
    if not path:
        return ""
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
        return value if re.fullmatch(r"[A-Za-z0-9_-]{32,512}", value) else ""
    except (OSError, UnicodeError):
        return ""


def configured() -> bool:
    operator, agent = token("operator"), token("agent")
    return bool(operator and agent and not hmac.compare_digest(operator.encode(), agent.encode()))


def runtime_root() -> Path:
    override = project_getenv("CROW_ENGINE_CONTROL_ROOT", "").strip()
    return Path(override).resolve() if override else resolve_project_data_root(Path(__file__).resolve().parents[1])


def authorize(headers, role: str) -> None:
    if not configured():
        raise RestartError("Restart control requires two distinct configured token files", 503)
    supplied = str(credential_header(headers, "X-Crow-Control-Token") or "")
    if not hmac.compare_digest(supplied.encode(), token(role).encode()):
        raise RestartError("Restart authorization rejected", 403)


def identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", value):
        raise RestartError("Invalid request_id", 400)
    return value


class RestartMailbox:
    def __init__(self, root: Path, *, now=None):
        self.path = Path(root) / "control" / "pc2-engine-restart.sqlite3"
        self.now = now or time.time

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE IF NOT EXISTS controller (id INTEGER PRIMARY KEY, heartbeat REAL NOT NULL)")
        connection.execute("""CREATE TABLE IF NOT EXISTS requests (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, created REAL NOT NULL,
            updated REAL NOT NULL, claim TEXT, result TEXT)""")
        connection.execute("CREATE TABLE IF NOT EXISTS request_aliases (id TEXT PRIMARY KEY, target TEXT NOT NULL)")
        return connection

    def transaction(self, operation):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now = self.now()
            connection.execute("UPDATE requests SET status='expired', updated=? WHERE status='requested' AND created<?", (now, now - 120))
            # An uncertain execution is never automatically leased for a second restart.
            connection.execute("UPDATE requests SET status='unknown', updated=? WHERE status='restarting' AND updated<?", (now, now - 600))
            result = operation(connection, now)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def public(row):
        return {key: row[key] for key in ("id", "status", "created", "updated", "result")} if row else None

    @staticmethod
    def online(connection, now):
        row = connection.execute("SELECT heartbeat FROM controller WHERE id=1").fetchone()
        return bool(row and 0 <= now - row[0] <= 30)

    def status(self):
        def read(connection, now):
            row = connection.execute("SELECT * FROM requests ORDER BY created DESC, rowid DESC LIMIT 1").fetchone()
            return {"available": self.online(connection, now), "request": self.public(row)}
        return self.transaction(read)

    def request(self, request_id: object):
        request_id = identifier(request_id)

        def enqueue(connection, now):
            existing = connection.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if not existing:
                existing = connection.execute("SELECT r.* FROM requests r JOIN request_aliases a ON a.target=r.id WHERE a.id=?", (request_id,)).fetchone()
            if existing:
                return {"ok": True, "created": False, "request": self.public(existing)}
            active = connection.execute("SELECT * FROM requests WHERE status IN (?, ?)", ACTIVE).fetchone()
            if active:
                # A coalesced ID stays bound even if its HTTP response is lost and
                # the client retries after the original restart has completed.
                connection.execute("INSERT INTO request_aliases VALUES (?, ?)", (request_id, active["id"]))
                return {"ok": True, "created": False, "request": self.public(active)}
            if not self.online(connection, now):
                raise RestartError("PC2 restart controller is offline", 503)
            connection.execute("INSERT INTO requests VALUES (?, 'requested', ?, ?, NULL, NULL)", (request_id, now, now))
            row = connection.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            return {"ok": True, "created": True, "request": self.public(row)}
        return self.transaction(enqueue)

    def poll(self):
        def claim(connection, now):
            connection.execute("INSERT INTO controller VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat", (now,))
            row = connection.execute("SELECT * FROM requests WHERE status='requested' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return {"ok": True, "command": None}
            nonce = secrets.token_hex(32)
            connection.execute("UPDATE requests SET status='restarting', updated=?, claim=? WHERE id=?", (now, nonce, row["id"]))
            return {"ok": True, "command": {"request_id": row["id"], "claim": nonce, "action": "restart_collection_workers"}}
        return self.transaction(claim)

    def finish(self, payload: dict):
        request_id = identifier(payload.get("request_id"))
        result = payload.get("result")
        if not isinstance(result, str) or result not in {"workers_ready", "restart_failed", "health_timeout", "controller_interrupted"}:
            raise RestartError("Invalid restart result", 400)

        def complete(connection, now):
            row = connection.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            claim = str(payload.get("claim") or "")
            if not row or not row["claim"] or not hmac.compare_digest(row["claim"].encode(), claim.encode()):
                raise RestartError("Invalid restart claim", 403)
            if row["status"] in {"succeeded", "failed", "unknown"} and row["result"] == result:
                return {"ok": True, "request": self.public(row)}
            if row["status"] != "restarting":
                raise RestartError("Restart claim is no longer active")
            status = "succeeded" if result == "workers_ready" else "unknown" if result == "controller_interrupted" else "failed"
            connection.execute("UPDATE requests SET status=?, updated=?, result=? WHERE id=?", (status, now, result, request_id))
            row = connection.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            return {"ok": True, "request": self.public(row)}
        return self.transaction(complete)
