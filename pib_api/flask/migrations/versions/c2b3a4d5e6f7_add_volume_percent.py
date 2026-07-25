"""add volume_percent to app_settings

Revision ID: c2b3a4d5e6f7
Revises: f1e2d3c4b5a6
Create Date: 2026-07-25 00:00:00.000000

Ergaenzt app_settings um volume_percent (Ausgabelautstaerke des Roboters,
0-100, Default 100) - einstellbar ueber den Lautstaerke-Regler unter System.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c2b3a4d5e6f7"
down_revision = "f1e2d3c4b5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "app_settings",
        sa.Column(
            "volume_percent",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )


def downgrade():
    op.drop_column("app_settings", "volume_percent")
