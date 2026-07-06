"""add gesture and movement_sequence tables

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-01 14:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "gesture",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gesture_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("deletable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("gesture_id"),
    )
    op.create_table(
        "gesture_motor_position",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("motor_name", sa.Integer(), nullable=False),
        sa.Column("gesture_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["motor_name"], ["motor.name"]),
        sa.ForeignKeyConstraint(["gesture_id"], ["gesture.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "movement_sequence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sequence_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("deletable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sample_rate_hz", sa.Float(), nullable=False, server_default="10.0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("sequence_id"),
    )
    op.create_table(
        "movement_sequence_frame",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("timestamp_ms", sa.Integer(), nullable=False),
        sa.Column("positions", sa.JSON(), nullable=False),
        sa.Column("sequence_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["sequence_id"], ["movement_sequence.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("movement_sequence_frame")
    op.drop_table("movement_sequence")
    op.drop_table("gesture_motor_position")
    op.drop_table("gesture")
