"""Bound libpq dead-peer detection without changing transaction semantics."""

from sqlalchemy.engine import make_url


def engine_connection_options(url: str) -> dict:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        return {}
    options = {"pool_pre_ping": True}
    if parsed.get_driver_name() not in {"psycopg", "psycopg2"}:
        return options
    # A lost NAS connection must not inherit the OS's multi-hour keepalive delay.
    # Explicit URL options remain authoritative, including intentional overrides.
    defaults = {
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
        "tcp_user_timeout": 60000,
    }
    options["connect_args"] = {
        key: value for key, value in defaults.items() if key not in parsed.query
    }
    return options
