
"""Fix GPS segment ID type.

Revision ID: fdcc49a631d9
Revises: 2e0868c1d3c0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fdcc49a631d9"
down_revision: Union[str, Sequence[str], None] = "2e0868c1d3c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("gps_road_speed_samples") as batch_op:
        batch_op.alter_column(
            "segment_id",
            existing_type=sa.Integer(),
            type_=sa.String(length=128),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("gps_road_speed_samples") as batch_op:
        batch_op.alter_column(
            "segment_id",
            existing_type=sa.String(length=128),
            type_=sa.Integer(),
            existing_nullable=False,
        )
