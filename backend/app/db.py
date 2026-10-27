"""Async SQLAlchemy engine and session. PostgreSQL in production, SQLite for dev and tests."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import MetaData, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

# Fixed constraint names, so later migrations can drop or alter them (SQLite batch mode needs names too).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Database:
    def __init__(self, url: str):
        self.url = url
        self.engine = create_async_engine(url, future=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        """Tables straight from the models, without migrations. Tests only: it never changes existing tables."""
        from . import models  # noqa: F401  (registers tables)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        from . import models  # noqa: F401
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def migrate(self) -> None:
        """Bring the schema up to date (`alembic upgrade head`). Used at dev startup."""
        async with self.engine.connect() as conn:
            tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        if "users" in tables and "alembic_version" not in tables:
            raise RuntimeError(
                "This database was created before migrations existed (issue 020), so Alembic can't tell "
                "which version it is at. Delete it once (for the default SQLite file: delete uberclone.db) "
                "and restart; from now on schema changes come as migrations.")
        # Alembic's env.py runs its own event loop, so it gets a worker thread.
        await asyncio.to_thread(run_migrations, self.url)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as s:
            yield s

    async def dispose(self) -> None:
        await self.engine.dispose()


def run_migrations(url: str, revision: str = "head") -> None:
    """`alembic upgrade <revision>` against `url`, callable from Python (startup, tests)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, revision)
