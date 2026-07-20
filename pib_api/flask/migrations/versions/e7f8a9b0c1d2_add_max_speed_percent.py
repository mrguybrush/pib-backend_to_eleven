"""add max_speed_percent to movement settings

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-07-19 00:00:00.000000

Ergaenzt die movement_settings-Tabelle um max_speed_percent (Sicherheits-
Obergrenze fuers globale Bewegungstempo, Default 100 = keine Begrenzung).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "movement_settings",
        sa.Column(
            "max_speed_percent",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )


def downgrade():
    op.drop_column("movement_settings", "max_speed_percent")
