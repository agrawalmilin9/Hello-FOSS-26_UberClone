
"""Persist candidate GPS road-learning samples without changing live routing."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from routing import VehicleType

from ..context import AppContext
from ..models import (
    GPSProcessedRide,
    GPSRoadSpeedSample,
    GPSRoadExposure,
    Ride,
    RideStatus,
)
from .gps_learning import (
    learn_ride_speeds, load_phase_pings, load_planned_segments,
    pings_to_observations, validated_ride_exposures,
)

log = logging.getLogger(__name__)

MAX_RIDES_PER_TICK = 100
PHASE = "trip"


class GPSLearningWorker:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                stats = await self.tick()
                log.info("GPS learning cycle: %s", stats)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("GPS learning cycle failed")

            await asyncio.sleep(
                self.ctx.settings.gps_learning_tick_seconds
            )

    async def tick(
        self,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Persist validated candidates; never refresh the live router."""
        async with self._lock:
            stats = {
                "rides_processed": 0,
                "speed_samples": 0,
                "rides_failed": 0,
            }

            router = self.ctx.routes.router
            if router is None:
                return stats

            now = now or datetime.now(timezone.utc)

            # Catch up on unprocessed completed rides, even after downtime.
            async with self.ctx.db.sessions() as session:
                processed = (
                    select(GPSProcessedRide.id)
                    .where(
                        GPSProcessedRide.ride_id == Ride.id,
                        GPSProcessedRide.phase == PHASE,
                    )
                    .exists()
                )

                result = await session.execute(
                    select(Ride)
                    .where(
                        Ride.status == RideStatus.COMPLETED,
                        Ride.completed_at <= now,
                        Ride.driver_id.is_not(None),
                        ~processed,
                    )
                    .order_by(Ride.completed_at, Ride.id)
                    .limit(MAX_RIDES_PER_TICK)
                )

                rides = list(result.scalars().all())

            for ride in rides:
                try:
                    vehicle = VehicleType(ride.vehicle_type)
                    service = router.services.get(vehicle)

                    if service is None:
                        continue

                    # One transaction per ride: samples and processed
                    # marker are committed together.
                    async with self.ctx.db.sessions() as session:
                        async with session.begin():
                            already_processed = await session.scalar(
                                select(GPSProcessedRide.id).where(
                                    GPSProcessedRide.ride_id == ride.id,
                                    GPSProcessedRide.phase == PHASE,
                                )
                            )

                            if already_processed is not None:
                                continue

                            samples = await learn_ride_speeds(
                                session,
                                ride.driver_id,
                                ride.id,
                                service.edges,
                                vehicle,
                                phase=PHASE,
                            )

                            for sample in samples:
                                session.add(
                                    GPSRoadSpeedSample(
                                        ride_id=ride.id,
                                        driver_id=ride.driver_id,
                                        segment_id=sample.segment_id,
                                        vehicle_type=vehicle.value,
                                        speed_kmh=sample.speed_kmh,
                                        observed_at=sample.observed_at,
                                    )
                                )

                            # Only persist GPS-verified followed segments.
                            # A nearest-road mismatch alone cannot prove
                            # intentional road avoidance.
                            planned = await load_planned_segments(
                                session, ride.driver_id, ride.id, PHASE,
                            )
                            pings = await load_phase_pings(
                                session, ride.driver_id, ride.id, PHASE,
                            ) if planned else []

                            exposures = validated_ride_exposures(
                                pings_to_observations(pings),
                                planned,
                                service.edges,
                                ride.driver_id,
                                ride.id,
                                vehicle,
                            ) if pings else []

                            seen_segments = set()

                            for exposure in exposures:
                                if exposure.segment_id not in service.edges:
                                    continue
                                if exposure.segment_id in seen_segments:
                                    continue

                                seen_segments.add(exposure.segment_id)

                                session.add(
                                    GPSRoadExposure(
                                        ride_id=ride.id,
                                        driver_id=ride.driver_id,
                                        phase=PHASE,
                                        segment_id=exposure.segment_id,
                                        vehicle_type=vehicle.value,
                                        followed=exposure.followed,
                                        observed_at=exposure.observed_at,
                                    )
                                )

                            session.add(
                                GPSProcessedRide(
                                    ride_id=ride.id,
                                    driver_id=ride.driver_id,
                                    phase=PHASE,
                                    vehicle_type=vehicle.value,
                                    sample_count=len(samples),
                                    processed_at=now,
                                )
                            )

                    stats["rides_processed"] += 1
                    stats["speed_samples"] += len(samples)

                except IntegrityError:
                    # A concurrent worker may have inserted the
                    # same processed-ride marker first.
                    log.info(
                        "GPS learning already recorded for ride %s",
                        ride.id,
                    )

                except asyncio.CancelledError:
                    raise

                except Exception:
                    stats["rides_failed"] += 1
                    log.exception(
                        "GPS learning failed for ride %s",
                        ride.id,
                    )

            return stats
