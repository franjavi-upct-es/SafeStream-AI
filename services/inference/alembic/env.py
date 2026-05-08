# services/inference/alembic/env.py
"""Alembic runtime environment.

Differences from a stock Alembic setup:

  * The DSN comes from the application settings, not from ``alembic.ini``.
    This lets us use the same ``POSTGRES_DSN`` env var that the service
    itself consumes, with no risk of drift.
  * The DSN is forced to the synchronous ``psycopg2`` driver here. The
    inference service uses ``asyncpg`` at runtime, but Alembic operates
    synchronously and reuses connection management from SQLAlchemy core.
  * ``target_metadata`` is None: we don't keep declarative ORM models;
    migrations are written by hand. Autogenerate is therefore disabled.
"""

from __future__ import annotations

import importlib.util
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from src.config import settings

# Load the local helper from the same directory as this env.py without
# touching sys.path - the file is shipped alongside the migrations.
_HELPER_PATH = Path(__file__).resolve().parent / "dsn.py"
_spec = importlib.util.spec_from_file_location(
    "_safestream_alembic_dsn",
    _HELPER_PATH,
)
assert _spec is not None and _spec.loader is not None
_dsn_helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dsn_helper)


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


config.set_main_option(
    "sqlalchemy.url",
    _dsn_helper.normalise_to_psycopg2(settings.postgres_dsn),
)

target_metadata = None  # hand-written migrations only


def run_migrations_offline() -> None:
    """Render SQL to stdout without executing - handy for review pipelines."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against the configured database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
