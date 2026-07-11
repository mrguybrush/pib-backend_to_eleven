"""add motion capture joint mapping table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-07 00:00:00.000000

Legt die motion_capture_joint_mapping-Tabelle an: pro-Installation-Override,
welche erkannte Koerperseite (links/rechts) welchen Robotermotor treibt.
Leer bis der Kalibrierungs-Assistent das erste Mal gespeichert wird - bis
dahin gelten die Defaults aus gesture_control/retargeting.py.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "motion_capture_joint_mapping",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("motor_name", sa.String(length=255), nullable=False),
        sa.Column(
            "source_side", sa.String(length=10), nullable=False, server_default="left"
        ),
        sa.Column(
            "invert", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("motor_name"),
    )


def downgrade():
    op.drop_table("motion_capture_joint_mapping")
