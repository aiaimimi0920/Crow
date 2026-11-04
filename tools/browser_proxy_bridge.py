"""Loopback authenticated proxy bridge with bounded, joined connection workers."""

from __future__ import annotations

import base64
import socket
import socketserver
import sys
import threading
from urllib.parse import unquote, urlsplit

BUFFER_SIZE = 65536
CONNECT_TIMEOUT = 25
IDLE_TIMEOUT = 120


def shutdown(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def pump(source: socket.socket, destination: socket.socket) -> None:
    try:
        while data := source.recv(BUFFER_SIZE):
            destination.sendall(data)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class Bridge:
    def __init__(self, upstream_url: str):
        parts = urlsplit(
            upstream_url if "://" in upstream_url else "http://" + upstream_url
        )
        if not parts.hostname:
            raise ValueError("Invalid upstream proxy address")
        self.address = (parts.hostname, parts.port or 8080)
        self.auth_header = None
        if parts.username:
            credentials = unquote(parts.username) + ":" + unquote(parts.password or "")
            token = base64.b64encode(credentials.encode("utf-8"))
            self.auth_header = b"Proxy-Authorization: Basic " + token

    def rewrite_head(self, head: bytes) -> bytes:
        lines = head.split(b"\r\n")
        result = [lines[0]]
        for line in lines[1:]:
            if line and not line.lower().startswith(
                (b"proxy-authorization:", b"proxy-connection:", b"connection:")
            ):
                result.append(line)
        if self.auth_header:
            result.append(self.auth_header)
        return b"\r\n".join([*result, b"Connection: keep-alive", b"", b""])


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client = self.request
        client.settimeout(self.server.idle_timeout)
        upstream = None
        worker = None
        try:
            buffered = b""
            while b"\r\n\r\n" not in buffered:
                chunk = client.recv(BUFFER_SIZE)
                if not chunk:
                    return
                buffered += chunk
                if len(buffered) > 1 << 17:
                    return
            head, _, body = buffered.partition(b"\r\n\r\n")
            try:
                upstream = socket.create_connection(
                    self.server.bridge.address, timeout=CONNECT_TIMEOUT
                )
            except OSError:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                return
            upstream.settimeout(self.server.idle_timeout)
            upstream.sendall(self.server.bridge.rewrite_head(head) + body)
            worker = threading.Thread(target=pump, args=(upstream, client), daemon=True)
            worker.start()
            pump(client, upstream)
            worker.join(timeout=self.server.join_grace)
        except OSError:
            pass
        finally:
            # close() alone does not wake another thread blocked in recv() on Linux.
            # Wake both directions before joining, including half-closed tunnels.
            for sock in (upstream, client):
                if sock is not None:
                    shutdown(sock)
            if worker is not None and worker.ident is not None:
                worker.join(timeout=self.server.join_grace)
            if upstream is not None:
                upstream.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128
    idle_timeout = IDLE_TIMEOUT
    join_grace = 5.0

    def __init__(self, address, bridge: Bridge, *, max_connections: int = 32):
        self.bridge = bridge
        self.slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: browser_proxy_bridge <upstream_url> <listen_port>")
    with Server(("127.0.0.1", int(sys.argv[2])), Bridge(sys.argv[1])) as server:
        print(
            "[proxy_bridge] loopback listener ready; connection workers bounded",
            flush=True,
        )
        server.serve_forever()


if __name__ == "__main__":
    main()
