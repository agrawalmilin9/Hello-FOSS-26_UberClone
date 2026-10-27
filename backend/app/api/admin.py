from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_session, require
from ..errors import not_found
from ..models import (
    ACTIVE_RIDE_STATUSES,
    DriverProfile,
    DriverStatus,
    Ride,
    RideStatus,
    Role,
    User,
)
from ..schemas import (
    AdminMapDriverOut,
    AdminMapOut,
    AdminMapRideOut,
    DriverProfileOut,
    PlaceIn,
    RideOut,
)
from ..services.rides import ride_out
from .drivers import profile_out

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require(Role.ADMIN)


@router.get("/drivers", response_model=list[DriverProfileOut])
async def list_drivers(status: DriverStatus | None = None, _: User = Depends(admin_only),
                       session: AsyncSession = Depends(get_session)) -> list[DriverProfileOut]:
    query = select(DriverProfile)
    if status:
        query = query.where(DriverProfile.status == status)
    return [profile_out(p) for p in await session.scalars(query)]


async def _set_driver_status(session: AsyncSession, user_id: str, status: DriverStatus) -> DriverProfileOut:
    profile = await session.get(DriverProfile, user_id)
    if profile is None:
        raise not_found("driver")
    profile.status = status
    if status is not DriverStatus.APPROVED:
        profile.is_online = False
    await session.commit()
    return profile_out(profile)


@router.post("/drivers/{user_id}/approve", response_model=DriverProfileOut)
async def approve(user_id: str, _: User = Depends(admin_only), session: AsyncSession = Depends(get_session)):
    return await _set_driver_status(session, user_id, DriverStatus.APPROVED)


@router.post("/drivers/{user_id}/suspend", response_model=DriverProfileOut)
async def suspend(user_id: str, _: User = Depends(admin_only), session: AsyncSession = Depends(get_session)):
    return await _set_driver_status(session, user_id, DriverStatus.SUSPENDED)


@router.get("/rides", response_model=list[RideOut])
async def list_rides(status: RideStatus | None = None, limit: int = Query(50, ge=1, le=200),
                     admin: User = Depends(admin_only), session: AsyncSession = Depends(get_session)) -> list[RideOut]:
    query = select(Ride).order_by(Ride.requested_at.desc()).limit(limit)
    if status:
        query = query.where(Ride.status == status)
    return [await ride_out(session, r, admin) for r in await session.scalars(query)]

@router.get("/map", response_model=AdminMapOut)
async def admin_map(
    _: User = Depends(admin_only),
    session: AsyncSession = Depends(get_session),
) -> AdminMapOut:
    driver_query = select(DriverProfile).where(
        DriverProfile.is_online.is_(True),
        DriverProfile.status == DriverStatus.APPROVED,
        DriverProfile.lat.is_not(None),
        DriverProfile.lng.is_not(None),
    )
    drivers = [
        AdminMapDriverOut(
            user_id=driver.user_id,
            vehicle_type=driver.vehicle_type,
            vehicle_number=driver.vehicle_number,
            lat=driver.lat,
            lng=driver.lng,
        )
        for driver in await session.scalars(driver_query)
    ]

    ride_query = (
        select(Ride)
        .where(Ride.status.in_(ACTIVE_RIDE_STATUSES))
        .order_by(Ride.requested_at.desc())
    )
    rides = [
        AdminMapRideOut(
            id=ride.id,
            status=ride.status,
            vehicle_type=ride.vehicle_type,
            pickup=PlaceIn(
                lat=ride.pickup_lat,
                lng=ride.pickup_lng,
            ),
            drop=PlaceIn(
                lat=ride.drop_lat,
                lng=ride.drop_lng,
            ),
            driver_id=ride.driver_id,
            requested_at=ride.requested_at,
        )
        for ride in await session.scalars(ride_query)
    ]

    return AdminMapOut(drivers=drivers, rides=rides)