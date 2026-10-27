"""Alembic migrations (issue 020): they build the models' schema, dev startup applies them,
and on PostgreSQL the dispatch cycle row-locks rides so a ride can't be assigned twice."""
from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from backend.app.config import Settings
from backend.app.db import ALEMBIC_INI, Base, Database, run_migrations
from backend.app.main import create_app
from backend.app.models import Ride, RideStatus
from backend.migrations.autogen import compare_type

from .conftest import database_url, driver, on_postgres, rider, tick
from .test_api import book

APP_TABLES = set(Base.metadata.tables)


def _run(url: str, fn):
    """Run fn(sync_connection) against url and return its result."""
    async def go():
        db = Database(url)
        try:
            async with db.engine.connect() as conn:
                return await conn.run_sync(fn)
        finally:
            await db.dispose()
    return asyncio.run(go())


def _tables(url: str) -> set[str]:
    return _run(url, lambda c: set(inspect(c).get_table_names()))


def _schema_diff(url: str) -> list:
    """What `alembic revision --autogenerate` would put in a new migration: empty when models and migrations agree."""
    def diff(conn):
        ctx = MigrationContext.configure(conn, opts={"compare_type": compare_type})
        return compare_metadata(ctx, Base.metadata)
    return _run(url, diff)


def test_migrations_build_the_models_schema(tmp_path):
    url = database_url(tmp_path)
    run_migrations(url)
    assert APP_TABLES | {"alembic_version"} <= _tables(url)
    # Fails when someone changes backend/app/models.py without adding a migration.
    assert _schema_diff(url) == []


def test_downgrade_and_upgrade_again(tmp_path):
    url = database_url(tmp_path)
    run_migrations(url)
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes.update(database_url=url, configure_logger=False)
    command.downgrade(cfg, "base")
    assert not APP_TABLES & _tables(url)
    run_migrations(url)
    assert _schema_diff(url) == []


def _dev_client(url: str) -> TestClient:
    return TestClient(create_app(Settings(env="dev", database_url=url, run_matching_loop=False, roads_path=None)))


def test_dev_startup_applies_migrations(tmp_path):
    url = database_url(tmp_path)
    for _ in range(2):                                   # the second start finds nothing to do
        with _dev_client(url) as client:
            assert client.get("/health").json() == {"status": "ok"}
            r = rider(client)                            # the schema works end to end
            assert r.get("/me").status_code == 200
    assert APP_TABLES | {"alembic_version"} <= _tables(url)


def test_dev_startup_explains_a_pre_migration_database(tmp_path):
    url = database_url(tmp_path)
    async def old_style():
        db = Database(url)
        await db.create_all()                            # what dev startup did before issue 020
        await db.dispose()
    asyncio.run(old_style())
    with pytest.raises(RuntimeError, match="before migrations existed"):
        with _dev_client(url):
            pass


@pytest.mark.skipif(not on_postgres, reason="row locks need PostgreSQL (set TEST_DATABASE_URL)")
def test_dispatch_skips_a_ride_locked_by_another_transaction(client):
    """While another transaction (a rider's cancel, another backend instance) holds the ride row,
    the dispatch cycle leaves that ride alone instead of assigning it."""
    r = rider(client)
    d = driver(client, 12.9726, 77.5946)
    ride = book(r)
    tick(client)
    assert d.post(f"/rides/{ride['id']}/accept").status_code == 202

    ctx = client.app.state.ctx
    dispatcher = client.app.state.dispatcher

    async def tick_while_locked() -> RideStatus:
        async with ctx.db.sessions() as other:
            await other.get(Ride, ride["id"], with_for_update=True)     # held until rollback
            await dispatcher.tick()
            await other.rollback()
        async with ctx.db.sessions() as s:
            return await s.scalar(select(Ride.status).where(Ride.id == ride["id"]))

    assert client.portal.call(tick_while_locked) is RideStatus.SEARCHING
    assert not d.events("ride:confirmed")

    tick(client)                                         # lock released: the next cycle assigns it
    assert r.get(f"/rides/{ride['id']}").json()["status"] == "driver_assigned"
    assert d.events("ride:confirmed")
