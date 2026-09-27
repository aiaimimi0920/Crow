"""Threaded collection API with bounded, independent TLS handshakes."""

import logging
import socket
import socketserver
import ssl
import threading
from collections.abc import Mapping
from pathlib import Path

from src.collection_job_control import DEFAULT_TIMEOUT_SECONDS, positive_timeout
from src.collection_jobs import CollectionJobManager, JobQueueFull

CERT_ENV = "FAPAI_API_TLS_CERT_FILE"
KEY_ENV = "FAPAI_API_TLS_KEY_FILE"


def tls_context(cert_file: str | None, key_file: str | None) -> ssl.SSLContext | None:
    cert_file = (cert_file or "").strip()
    key_file = (key_file or "").strip()
    if not cert_file and not key_file:
        return None
    if not cert_file or not key_file:
        raise ValueError("Collection API TLS requires both certificate and key files")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Never prompt an unattended process for an encrypted key password.
    context.load_cert_chain(cert_file, key_file, password=lambda: "")
    return context


def tls_context_from_env(env: Mapping[str, str]) -> ssl.SSLContext | None:
    return tls_context(env.get(CERT_ENV), env.get(KEY_ENV))


class CollectionHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    handshake_timeout = 5.0

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[socketserver.BaseRequestHandler],
        bind_and_activate: bool = True,
        *,
        tls: ssl.SSLContext | None = None,
        job_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.tls = tls
        self._job_timeout = positive_timeout(job_timeout_seconds)
        self._jobs_lock = threading.Lock()
        self._jobs: CollectionJobManager | None = None
        self._jobs_root: Path | None = None
        self._closing = False
        super().__init__(server_address, handler, bind_and_activate)

    def collection_jobs(self, data_root: Path) -> CollectionJobManager:
        root = data_root.resolve()
        with self._jobs_lock:
            if self._closing:
                raise JobQueueFull("Collection API is closing")
            if self._jobs is None:
                self._jobs = CollectionJobManager(
                    root, timeout_seconds=self._job_timeout
                )
                self._jobs_root = root
            if self._jobs_root != root:
                raise ValueError("Collection job data root changed; restart the API")
            return self._jobs

    def server_close(self) -> None:
        with self._jobs_lock:
            self._closing = True
            jobs = self._jobs
        if jobs is not None and not jobs.close(timeout=5):
            logging.getLogger(__name__).warning(
                "Collection maintenance shutdown is pending worker exit"
            )
        super().server_close()

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        connection, address = super().get_request()
        if self.tls is None:
            return connection, address
        secured = None
        try:
            connection.settimeout(self.handshake_timeout)
            secured = self.tls.wrap_socket(
                connection, server_side=True, do_handshake_on_connect=False
            )
            return secured, address
        except BaseException:
            # Also release the accepted descriptor when shutdown interrupts TLS.
            (secured if secured is not None else connection).close()
            raise

    def process_request_thread(
        self,
        request: socket.socket | tuple[bytes, socket.socket],
        client_address: tuple[str, int],
    ) -> None:
        if isinstance(request, ssl.SSLSocket):
            try:
                # Handshake I/O must never occupy the accept loop.
                request.do_handshake()
                request.settimeout(None)
            except OSError:
                self.shutdown_request(request)
                return
            except BaseException:
                self.shutdown_request(request)
                raise
        super().process_request_thread(request, client_address)
