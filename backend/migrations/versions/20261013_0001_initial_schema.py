"""Initial schema: the tables in backend/app/models.py as of issue 020.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    # Same as models._enum: stored as VARCHAR(32), no native PostgreSQL enum type.
    return sa.Enum(*values, name=name, native_enum=False, length=32)


ROLE = ("rider", "driver", "admin")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("phone", sa.String(16), nullable=False),
        sa.Column("name", sa.String(80), nullable=True),
        sa.Column("role", _enum("role", *ROLE), nullable=False),
        sa.Column("rating_sum", sa.Integer(), nullable=False),
        sa.Column("rating_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)

    op.create_table(
        "otp_codes",
        sa.Column("phone", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("phone", name="pk_otp_codes"),
    )

    op.create_table(
        "driver_profiles",
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("vehicle_type", sa.String(16), nullable=False),
        sa.Column("vehicle_number", sa.String(16), nullable=False),
        sa.Column("vehicle_model", sa.String(60), nullable=True),
        sa.Column("status", _enum("driverstatus", "pending", "approved", "suspended"), nullable=False),
        sa.Column("is_online", sa.Boolean(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("heading", sa.Float(), nullable=True),
        sa.Column("location_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_driver_profiles_user_id_users"),
        sa.PrimaryKeyConstraint("user_id", name="pk_driver_profiles"),
    )

    op.create_table(
        "rides",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("rider_id", sa.String(32), nullable=False),
        sa.Column("driver_id", sa.String(32), nullable=True),
        sa.Column("vehicle_type", sa.String(16), nullable=False),
        sa.Column("status", _enum("ridestatus", "searching", "driver_assigned", "driver_arrived", "in_progress",
                                  "completed", "cancelled", "no_drivers"), nullable=False),
        sa.Column("pickup_lat", sa.Float(), nullable=False),
        sa.Column("pickup_lng", sa.Float(), nullable=False),
        sa.Column("pickup_address", sa.String(200), nullable=True),
        sa.Column("drop_lat", sa.Float(), nullable=False),
        sa.Column("drop_lng", sa.Float(), nullable=False),
        sa.Column("drop_address", sa.String(200), nullable=True),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("fare_estimate_paise", sa.Integer(), nullable=False),
        sa.Column("fare_final_paise", sa.Integer(), nullable=True),
        sa.Column("pin", sa.String(4), nullable=False),
        sa.Column("payment_method", _enum("paymentmethod", "cash", "online"), nullable=False),
        sa.Column("payment_status", _enum("paymentstatus", "pending", "paid"), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("searching_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", _enum("role", *ROLE), nullable=True),
        sa.Column("cancel_reason", sa.String(200), nullable=True),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], name="fk_rides_rider_id_users"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], name="fk_rides_driver_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_rides"),
    )
    op.create_index("ix_rides_rider_id", "rides", ["rider_id"])
    op.create_index("ix_rides_driver_id", "rides", ["driver_id"])
    op.create_index("ix_rides_status", "rides", ["status"])

    op.create_table(
        "ride_offers",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("ride_id", sa.String(32), nullable=False),
        sa.Column("driver_id", sa.String(32), nullable=False),
        sa.Column("status", _enum("offerstatus", "pinged", "accepted", "rejected", "won", "lost", "expired",
                                  "released"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], name="fk_ride_offers_ride_id_rides"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], name="fk_ride_offers_driver_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_ride_offers"),
        sa.UniqueConstraint("ride_id", "driver_id", "created_at",
                            name="uq_ride_offers_ride_id_driver_id_created_at"),
    )
    op.create_index("ix_ride_offers_ride_id", "ride_offers", ["ride_id"])
    op.create_index("ix_ride_offers_driver_id", "ride_offers", ["driver_id"])
    op.create_index("ix_ride_offers_status", "ride_offers", ["status"])

    op.create_table(
        "ratings",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("ride_id", sa.String(32), nullable=False),
        sa.Column("from_user_id", sa.String(32), nullable=False),
        sa.Column("to_user_id", sa.String(32), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], name="fk_ratings_ride_id_rides"),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"], name="fk_ratings_from_user_id_users"),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"], name="fk_ratings_to_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_ratings"),
        sa.UniqueConstraint("ride_id", "from_user_id", name="uq_ratings_ride_id_from_user_id"),
    )

    op.create_table(
        "location_pings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("driver_id", sa.String(32), nullable=False),
        sa.Column("ride_id", sa.String(32), nullable=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("speed_kmh", sa.Float(), nullable=True),
        sa.Column("heading", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], name="fk_location_pings_driver_id_users"),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], name="fk_location_pings_ride_id_rides"),
        sa.PrimaryKeyConstraint("id", name="pk_location_pings"),
    )
    op.create_index("ix_location_pings_driver_id", "location_pings", ["driver_id"])
    op.create_index("ix_location_pings_recorded_at", "location_pings", ["recorded_at"])


def downgrade() -> None:
    op.drop_table("location_pings")
    op.drop_table("ratings")
    op.drop_table("ride_offers")
    op.drop_table("rides")
    op.drop_table("driver_profiles")
    op.drop_table("otp_codes")
    op.drop_table("users")
