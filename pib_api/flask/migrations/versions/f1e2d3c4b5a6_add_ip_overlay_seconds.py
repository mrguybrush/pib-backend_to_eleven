"""add ip_overlay_seconds to app_settings

Revision ID: f1e2d3c4b5a6
Revises: f8c4a8964459
Create Date: 2026-07-21 00:00:00.000000

Ergaenzt app_settings um ip_overlay_seconds (einstellbare Anzeigedauer des
IP/QR-Code-Overlays beim Hochfahren, Default 20s wie bisher fest verdrahtet
in ros-display. 0 = Overlay wird nicht angezeigt).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f1e2d3c4b5a6"
down_revision = "f8c4a8964459"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "app_settings",
        sa.Column(
            "ip_overlay_seconds",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
    )


def downgrade():
    op.drop_column("app_settings", "ip_overlay_seconds")
