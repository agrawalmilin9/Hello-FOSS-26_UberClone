"""Alembic environment: runs migrations with the app's async engine against DATABASE_URL."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app import models  # noqa: F401  (registers every table on Base.metadata)
from backend.app.config import settings
from backend.app.db import Base
from backend.migrations.autogen import compare_type, render_item

config = context.config

# The CLI configures logging from alembic.ini; the app's startup migration keeps uvicorn's logging as is.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    # Database.migrate() passes its own URL; the CLI uses DATABASE_URL like the app does.
    return config.attributes.get("database_url") or settings.database_url


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=compare_type,
        render_item=render_item,
        # SQLite can't ALTER most things; batch mode rebuilds the table instead. No effect on PostgreSQL.
        render_as_batch=_url().startswith("sqlite"),
        **kwargs,
    )


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_sync)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
