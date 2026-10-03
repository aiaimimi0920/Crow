"""Single-flight, revisioned settings mailbox; secrets never enter public snapshots."""
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

from .collection_engine_restart import RestartError, identifier
from .collection_settings_fingerprint import create_fingerprint, verify_fingerprint
from .collection_settings_schema import validate, validate_key


class SettingsStore:
    def __init__(self, root, *, now=time.time):
        self.root = Path(root) / "control" / "collection-settings"
        self.now = now

    def transaction(self, action):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix" and (self.root.is_symlink() or self.root.stat().st_uid != os.geteuid() or self.root.stat().st_mode & 0o077):
            raise RestartError("Settings storage permissions are unsafe", 503)
        connection = sqlite3.connect(self.root / "state.sqlite3", isolation_level=None, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, revision INTEGER, desired TEXT, effective TEXT, heartbeat REAL, key_present INTEGER)")
            connection.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, revision INTEGER, config TEXT, key_ref TEXT, fingerprint TEXT, status TEXT, claim TEXT, created REAL, updated REAL, result TEXT, previous TEXT)")
            connection.execute("BEGIN IMMEDIATE")
            now = self.now()
            connection.execute("UPDATE requests SET status='expired' WHERE status='requested' AND created<?", (now - 120,))
            connection.execute("UPDATE requests SET status='unknown' WHERE status='applying' AND updated<?", (now - 900,))
            result = action(connection, now)
            connection.commit()
            # Claims are never replayed, so only unclaimed requests need their secret.
            for row in connection.execute("SELECT id,key_ref FROM requests WHERE key_ref IS NOT NULL AND status!='requested'").fetchall():
                try:
                    (self.root / row["key_ref"]).unlink(missing_ok=True)
                    connection.execute("UPDATE requests SET key_ref=NULL WHERE id=?", (row["id"],))
                except (OSError, sqlite3.Error):
                    pass
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def public_request(row):
        return {key: row[key] for key in ("id", "revision", "status", "created", "updated", "result")} if row else None

    def status(self):
        def read(db, now):
            row = db.execute("SELECT * FROM state WHERE id=1").fetchone()
            request = db.execute("SELECT * FROM requests ORDER BY revision DESC LIMIT 1").fetchone()
            return {"ok": True, "available": bool(row and 0 <= now - row["heartbeat"] <= 30),
                    "revision": row["revision"] if row else 0,
                    "desired": json.loads(row["desired"]) if row else None,
                    "effective": json.loads(row["effective"]) if row else None,
                    "api_key_configured": bool(row and row["key_present"]),
                    "request": self.public_request(request)}
        return self.transaction(read)

    def apply(self, payload):
        if set(payload) != {"request_id", "expected_revision", "config", "api_key"}:
            raise RestartError("Invalid settings request fields", 400)
        request_id = identifier(payload["request_id"])
        config, key = validate(payload["config"]), validate_key(payload["api_key"])
        encoded = json.dumps(config, sort_keys=True, separators=(",", ":"))

        def enqueue(db, now):
            existing = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if existing:
                matches, needs_upgrade = verify_fingerprint(existing["fingerprint"], encoded, key)
                if not matches:
                    raise RestartError("Request ID is already bound to different settings")
                if needs_upgrade:
                    db.execute("UPDATE requests SET fingerprint=? WHERE id=?",
                               (create_fingerprint(encoded, key), request_id))
                return {"ok": True, "request": self.public_request(existing)}
            row = db.execute("SELECT * FROM state WHERE id=1").fetchone()
            if not row or not 0 <= now - row["heartbeat"] <= 30:
                raise RestartError("PC2 settings controller is offline", 503)
            if type(payload["expected_revision"]) is not int or payload["expected_revision"] != row["revision"]:
                raise RestartError("Settings changed; reload before applying")
            if db.execute("SELECT 1 FROM requests WHERE status IN ('requested','applying','unknown')").fetchone():
                raise RestartError("A settings operation is active or unconfirmed; inspect PC2 before continuing")
            fingerprint = create_fingerprint(encoded, key)
            reference = None
            if key:
                reference = secrets.token_hex(24)
                descriptor = os.open(self.root / reference, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(key)
                    stream.flush()
                    os.fsync(stream.fileno())
            revision = row["revision"] + 1
            db.execute("INSERT INTO requests VALUES (?,?,?,?,?,'requested',NULL,?,?,NULL,?)",
                       (request_id, revision, encoded, reference, fingerprint, now, now, row["effective"]))
            db.execute("UPDATE state SET revision=?, desired=? WHERE id=1", (revision, encoded))
            return {"ok": True, "request": self.public_request(db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone())}
        return self.transaction(enqueue)

    def poll(self, payload):
        if set(payload) != {"effective", "api_key_configured"} or type(payload["api_key_configured"]) is not bool:
            raise RestartError("Invalid controller inventory", 400)
        effective = json.dumps(validate(payload["effective"]), sort_keys=True)

        def claim(db, now):
            previous = db.execute("SELECT * FROM state WHERE id=1").fetchone()
            active = db.execute("SELECT 1 FROM requests WHERE status IN ('requested','applying','unknown')").fetchone()
            if previous and not active and json.loads(previous["effective"]) != json.loads(effective):
                db.execute("UPDATE state SET revision=revision+1,desired=? WHERE id=1", (effective,))
            db.execute("INSERT INTO state VALUES (1,0,?,?,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat, effective=excluded.effective, key_present=excluded.key_present",
                       (effective, effective, now, int(payload["api_key_configured"])))
            row = db.execute("SELECT * FROM requests WHERE status='requested' ORDER BY revision LIMIT 1").fetchone()
            if not row:
                return {"ok": True, "command": None}
            key = (self.root / row["key_ref"]).read_text(encoding="utf-8") if row["key_ref"] else None
            nonce = secrets.token_hex(32)
            db.execute("UPDATE requests SET status='applying',claim=?,updated=? WHERE id=?", (nonce, now, row["id"]))
            return {"ok": True, "command": {"request_id": row["id"], "revision": row["revision"], "claim": nonce,
                    "config": json.loads(row["config"]), "previous": json.loads(row["previous"]), "api_key": key}}
        return self.transaction(claim)

    def finish(self, payload):
        if set(payload) != {"request_id", "claim", "result", "effective", "api_key_configured"}:
            raise RestartError("Invalid settings receipt fields", 400)
        request_id = identifier(payload["request_id"])
        result = payload["result"]
        if result not in ("applied", "rolled_back", "rejected", "interrupted") or type(payload["api_key_configured"]) is not bool:
            raise RestartError("Invalid settings receipt", 400)
        effective = None if result == "interrupted" and payload["effective"] is None else validate(payload["effective"])
        if result == "interrupted" and effective is not None:
            raise RestartError("An uncertain receipt cannot claim effective settings", 400)

        def complete(db, now):
            row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            supplied_claim = str(payload["claim"]).encode("utf-8")
            stored_claim = str(row["claim"]).encode("utf-8") if row and row["claim"] else b""
            if not row or not stored_claim or not hmac.compare_digest(supplied_claim, stored_claim):
                raise RestartError("Invalid settings claim", 403)
            if row["result"] == result:
                return {"ok": True, "request": self.public_request(row)}
            if row["status"] not in ("applying", "unknown"):
                raise RestartError("Settings claim is no longer active")
            if db.execute("SELECT revision FROM state WHERE id=1").fetchone()[0] != row["revision"]:
                raise RestartError("Receipt is not for the current settings revision")
            if result == "applied" and effective != json.loads(row["config"]):
                raise RestartError("Effective settings do not match requested revision")
            if result == "rolled_back" and effective != json.loads(row["previous"]):
                raise RestartError("Failed apply must confirm the previous settings")
            if result == "rejected" and effective not in (json.loads(row["previous"]), json.loads(db.execute("SELECT effective FROM state WHERE id=1").fetchone()[0])):
                raise RestartError("Rejected apply must match observed settings")
            status = "succeeded" if result == "applied" else "unknown" if result == "interrupted" else "failed"
            db.execute("UPDATE requests SET status=?,result=?,updated=? WHERE id=?", (status, result, now, request_id))
            if effective is not None:
                db.execute("UPDATE state SET effective=?,heartbeat=?,key_present=? WHERE id=1",
                           (json.dumps(effective), now, int(payload["api_key_configured"])))
            return {"ok": True, "request": self.public_request(db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone())}
        return self.transaction(complete)
