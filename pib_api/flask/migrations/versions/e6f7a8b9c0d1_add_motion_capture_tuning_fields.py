"""add motion capture tuning fields

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-17 00:00:00.000000

Erweitert motion_capture_joint_mapping um scale/min_deg/max_deg/dead_zone_deg,
damit die Winkel-Uebersetzung (Kamera-Grad -> Motor-Centigrad) pro Gelenk
in der Zuordnungstabelle einstellbar ist, statt fest in retargeting.py zu
stehen. Bestehende Zeilen bekommen scale=100/dead_zone_deg=0 als generischen
Default (min_deg/max_deg bleiben NULL = keine Begrenzung) - der Nutzer kann
jede Zeile ueber die Tabelle sofort selbst nachjustieren.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("motion_capture_joint_mapping") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scale", sa.Float(), nullable=False, server_default="100.0"
            )
        )
        batch_op.add_column(sa.Column("min_deg", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("max_deg", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "dead_zone_deg", sa.Float(), nullable=False, server_default="0.0"
            )
        )


def downgrade():
    with op.batch_alter_table("motion_capture_joint_mapping") as batch_op:
        batch_op.drop_column("dead_zone_deg")
        batch_op.drop_column("max_deg")
        batch_op.drop_column("min_deg")
        batch_op.drop_column("scale")
