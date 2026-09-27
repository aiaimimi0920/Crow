"""Production collection API entrypoint; no postprocessing composition."""

import argparse
import logging
import os
import signal
import ssl
import threading

from .collection_application import CollectionApplication, create_application
from .collection_http_server import tls_context_from_env


def serve_application(
    app: CollectionApplication,
    address: tuple[str, int],
    *,
    tls: ssl.SSLContext | None = None,
) -> int:
    def stop(_signal: int, _frame: object) -> None:
        raise KeyboardInterrupt

    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.signal(signal.SIGTERM, stop)
    try:
        with app.http_server(address, tls=tls) as httpd:
            app.start()
            logging.getLogger(__name__).info(
                "Collection API listening on %s; data=%s",
                httpd.server_address,
                app.host.DATA_DIR,
            )
            httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            app.close()
        finally:
            if previous is not None:
                signal.signal(signal.SIGTERM, previous)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--data-root")
    args = parser.parse_args(argv)
    listener_tls = tls_context_from_env(os.environ)
    return serve_application(
        create_application(data_root=args.data_root),
        (args.host, args.port),
        tls=listener_tls,
    )


if __name__ == "__main__":
    raise SystemExit(main())
