"""App-scoped TLS control endpoint. No business database or Docker access."""

import argparse
import json
import os
import socket
import sqlite3
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.collection_engine_restart import (
    PREFIX as RESTART,
)
from src.collection_engine_restart import (
    RestartError,
    RestartMailbox,
    authorize,
    configured,
)
from src.collection_settings_schema import PREFIX, ROLES
from src.collection_settings_store import SettingsStore
from src.project_data_paths import resolve_project_data_root
from tools.collection_runtime_proxy import RUNTIME_ROUTES, forward_runtime


def dispatch(root, method, path, headers, body):
    if path in RUNTIME_ROUTES:
        authorize(headers, "operator")
        return forward_runtime(method, path, body)
    role = ROLES.get(path)
    if path in {RESTART, RESTART + "/poll", RESTART + "/result"}:
        role = "operator" if path == RESTART else "agent"
    if role is None or (method == "GET" and path not in {PREFIX, RESTART}):
        raise RestartError("Unsupported control route", 404)
    authorize(headers, role)
    if path.startswith(PREFIX):
        store = SettingsStore(root)
        if method == "GET":
            return store.status()
        action = path.rsplit("/", 1)[-1]
        if action not in {"apply", "poll", "result"}:
            raise RestartError("Unsupported control action", 405)
        return {"apply": store.apply, "poll": store.poll, "result": store.finish}[
            action
        ](body)
    store = RestartMailbox(root)
    if method == "GET":
        return {"ok": True, **store.status()}
    if path == RESTART:
        if set(body) != {"request_id"}:
            raise RestartError("Invalid restart request", 400)
        return store.request(body["request_id"])
    if path.endswith("/poll"):
        if body:
            raise RestartError("Invalid poll request", 400)
        return store.poll()
    return store.finish(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "CrowControl"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args):
        pass

    def respond(self, code, value):
        raw = json.dumps(value, ensure_ascii=True).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

    def reject(self, status, code):
        self.close_connection = True
        self.respond(status, {"ok": False, "code": code})
        # Do not lose a rejection to a TCP reset from an unread upload.
        try:
            self.connection.shutdown(socket.SHUT_WR)
            length = int(self.headers.get("Content-Length", "0"))
            if 0 < length <= 16384:
                self.connection.settimeout(0.1)
                self.rfile.read(length)
        except (OSError, ValueError):
            pass

    def handle_control(self):
        try:
            if self.headers.get("Transfer-Encoding"):
                raise RestartError("Transfer encoding is unsupported", 400)
            body = {}
            if self.command == "POST":
                content_type = (
                    str(self.headers.get("Content-Type") or "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if content_type != "application/json":
                    raise RestartError("Content-Type must be application/json", 415)
                length = int(self.headers.get("Content-Length", "0"))
                if not 2 <= length <= 16384:
                    raise RestartError("Invalid request size", 413)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("incomplete request body")
                body = json.loads(raw.decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("object required")
            result = dispatch(
                self.server.runtime_root, self.command, self.path, self.headers, body
            )
            self.respond(200, result)
        except RestartError as error:
            self.reject(error.status, "CONTROL_REJECTED")
        except (ValueError, TypeError, UnicodeError):
            self.reject(400, "CONTROL_INVALID")
        except (OSError, sqlite3.Error):
            self.reject(503, "CONTROL_UNAVAILABLE")

    do_GET = handle_control
    do_POST = handle_control


def create_server(address, root, cert_file, key_file):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_file, key_file)
    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    server.runtime_root = Path(root)
    server.socket = context.wrap_socket(
        server.socket, server_side=True, do_handshake_on_connect=False
    )
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18443)
    parser.add_argument("--cert-file", required=True, type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--runtime-root", type=Path, default=None)
    args = parser.parse_args()
    if args.runtime_root is None:
        args.runtime_root = resolve_project_data_root(
            Path(__file__).resolve().parents[1]
        )
    if not configured():
        parser.error("Two distinct operator/agent token files are required")
    os.umask(0o077)
    with create_server(
        (args.bind, args.port), args.runtime_root, args.cert_file, args.key_file
    ) as server:
        print("Crow HTTPS control ready", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
