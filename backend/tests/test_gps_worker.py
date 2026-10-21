
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select

from routing import VehicleType

from app.db import Database
from app.models import (
    GPSProcessedRide,
    GPSRoadSpeedSample,
    Ride,
    RideStatus,
    User,
)
from app.services.gps_worker import GPSLearningWorker


NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


async def make_worker(tmp_path):
    db = Database(
        f"sqlite+aiosqlite:///{(tmp_path / 'gps_worker.db').as_posix()}"
    )
    await db.create_all()

    async with db.sessions() as session:
        async with session.begin():
            session.add_all([
                User(id="rider-1", phone="1111111111"),
                User(id="driver-1", phone="2222222222"),
            ])

            session.add(
                Ride(
                    id="ride-1",
                    rider_id="rider-1",
                    driver_id="driver-1",
                    vehicle_type="car",
                    status=RideStatus.COMPLETED,
                    pickup_lat=19.0,
                    pickup_lng=72.0,
                    drop_lat=19.1,
                    drop_lng=72.1,
                    distance_m=1000,
                    duration_s=300,
                    fare_estimate_paise=10000,
                    pin="1234",
                    completed_at=NOW,
                )
            )

    service = SimpleNamespace(edges={})
    router = SimpleNamespace(
        services={VehicleType.CAR: service},
        refresh_telemetry=MagicMock(),
    )

    ctx = SimpleNamespace(
        db=db,
        routes=SimpleNamespace(router=router),
        settings=SimpleNamespace(
            gps_learning_tick_seconds=900,
        ),
    )

    return GPSLearningWorker(ctx), db


def sample():
    return SimpleNamespace(
        segment_id="12",
        speed_kmh=24.5,
        observed_at=NOW,
    )


def test_worker_persists_samples(tmp_path):
    async def scenario():
        worker, db = await make_worker(tmp_path)

        try:
            with patch(
                "app.services.gps_worker.learn_ride_speeds",
                new_callable=AsyncMock,
                return_value=[sample(), sample()],
            ):
                stats = await worker.tick(NOW)

            assert stats == {
                "rides_processed": 1,
                "speed_samples": 2,
                "rides_failed": 0,
            }

            async with db.sessions() as session:
                processed = (
                    await session.scalars(
                        select(GPSProcessedRide)
                    )
                ).all()
                speeds = (
                    await session.scalars(
                        select(GPSRoadSpeedSample)
                    )
                ).all()

            assert len(processed) == 1
            assert processed[0].sample_count == 2
            assert len(speeds) == 2
            assert speeds[0].segment_id == "12"
            assert speeds[0].speed_kmh == 24.5

        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_worker_deduplicates_across_restart(tmp_path):
    async def scenario():
        worker, db = await make_worker(tmp_path)

        try:
            with patch(
                "app.services.gps_worker.learn_ride_speeds",
                new_callable=AsyncMock,
                return_value=[sample()],
            ) as learn:
                first = await worker.tick(NOW)

                restarted = GPSLearningWorker(worker.ctx)
                second = await restarted.tick(NOW)

            assert first["rides_processed"] == 1
            assert second["rides_processed"] == 0
            assert learn.await_count == 1

        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_worker_retries_failed_ride(tmp_path):
    async def scenario():
        worker, db = await make_worker(tmp_path)

        try:
            with patch(
                "app.services.gps_worker.learn_ride_speeds",
                new_callable=AsyncMock,
                side_effect=[
                    RuntimeError("temporary error"),
                    [sample()],
                ],
            ):
                first = await worker.tick(NOW)
                second = await worker.tick(NOW)

            assert first["rides_failed"] == 1
            assert first["rides_processed"] == 0
            assert second["rides_processed"] == 1

            async with db.sessions() as session:
                records = (
                    await session.scalars(
                        select(GPSProcessedRide)
                    )
                ).all()

            assert len(records) == 1

        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_worker_without_road_data(tmp_path):
    async def scenario():
        worker, db = await make_worker(tmp_path)

        try:
            worker.ctx.routes.router = None
            stats = await worker.tick(NOW)

            assert stats["rides_processed"] == 0

        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_worker_does_not_refresh_live_router(tmp_path):
    async def scenario():
        worker, db = await make_worker(tmp_path)

        try:
            with patch(
                "app.services.gps_worker.learn_ride_speeds",
                new_callable=AsyncMock,
                return_value=[sample()],
            ):
                await worker.tick(NOW)

            worker.ctx.routes.router.refresh_telemetry.assert_not_called()

        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_worker_start_and_stop(tmp_path):
    async def scenario():
        worker, db = await make_worker(tmp_path)

        try:
            worker.ctx.routes.router = None
            worker.start()

            assert worker._task is not None

            await worker.stop()
            assert worker._task is None

        finally:
            await db.dispose()

    asyncio.run(scenario())
