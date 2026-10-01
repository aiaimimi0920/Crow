from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url
from src.project_environment import getenv as project_getenv
from src.storage.models import Base
from src.storage.migration_metadata import extension_table_filter, metadata_for_dialect


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = project_getenv("CROW_DB_URL") or config.get_main_option("sqlalchemy.url")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def _offline_target_metadata(url: str):
    """Build the same dialect-specific metadata used by online migrations."""
    try:
        dialect_name = make_url(url).get_backend_name()
    except (TypeError, ValueError):
        dialect_name = None
    return metadata_for_dialect(dialect_name) if dialect_name else target_metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=_offline_target_metadata(url),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    existing_connection = config.attributes.get("connection")
    if existing_connection is not None:
        configure_connection(existing_connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    if not database_url:
        raise RuntimeError("FAPAI_DB_URL is required for schema migration")
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        configure_connection(connection)

        with context.begin_transaction():
            context.run_migrations()


def configure_connection(connection):
    context.configure(
        connection=connection,
        target_metadata=metadata_for_dialect(connection.dialect.name),
        include_object=extension_table_filter(connection),
        compare_type=True,
    )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
