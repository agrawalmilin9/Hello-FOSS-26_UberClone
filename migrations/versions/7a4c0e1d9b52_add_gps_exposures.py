"""Persist GPS candidate road exposures.

Revision ID: 7a4c0e1d9b52
Revises: fdcc49a631d9
"""
from alembic import op
import sqlalchemy as sa

revision = "7a4c0e1d9b52"
down_revision = "fdcc49a631d9"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "gps_road_exposures",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("ride_id", sa.String(32), sa.ForeignKey("rides.id"), nullable=False),
        sa.Column("driver_id", sa.String(32), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("segment_id", sa.String(128), nullable=False),
        sa.Column("vehicle_type", sa.String(16), nullable=False),
        sa.Column("followed", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ride_id", "phase", "segment_id"),
    )
    op.create_index("ix_gps_road_exposures_ride_id", "gps_road_exposures", ["ride_id"])
    op.create_index("ix_gps_road_exposures_segment_id", "gps_road_exposures", ["segment_id"])

def downgrade():
    op.drop_index("ix_gps_road_exposures_segment_id", table_name="gps_road_exposures")
    op.drop_index("ix_gps_road_exposures_ride_id", table_name="gps_road_exposures")
    op.drop_table("gps_road_exposures")
