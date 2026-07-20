"""add motion capture zero offset

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-17 00:00:00.000000

Ergaenzt motion_capture_joint_mapping um zero_offset_deg: der rohe
Kamera-Kandidatenwert, den der Nutzer bei entspannt haengendem/neutralem
Gelenk tatsaechlich abliest (z.B. 70 Grad statt der idealisiert erwarteten
0 Grad, je nach Kamera-/Koerpergeometrie) - wird vor Totzone/Min/Max/
Skalierung vom rohen Kandidatenwert abgezogen, damit "Ruhehaltung" wirklich
auf 0 kalibriert werden kann statt fest bei 0 anzunehmen.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("motion_capture_joint_mapping") as batch_op:
        batch_op.add_column(
            sa.Column(
                "zero_offset_deg", sa.Float(), nullable=False, server_default="0.0"
            )
        )


def downgrade():
    with op.batch_alter_table("motion_capture_joint_mapping") as batch_op:
        batch_op.drop_column("zero_offset_deg")
