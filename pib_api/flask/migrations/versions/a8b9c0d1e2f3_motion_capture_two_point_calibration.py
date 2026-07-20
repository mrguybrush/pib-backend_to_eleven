"""motion capture two-point calibration

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-17 00:00:00.000000

Ersetzt das bisherige Skalierung/Totzone/Nullpunkt-Modell (verwirrend, siehe
Nutzer-Feedback) durch eine Zwei-Punkt-Kalibrierung: candidate_low_deg/
candidate_high_deg sind die rohen Kamera-Ablesungen bei Gelenk "unten"/"oben"
(per "Ist-Wert"-Button gesetzt), werden linear auf die volle physische Spanne
des jeweiligen Servos (rotation_range_min/max) abgebildet - kein manuelles
Skalieren mehr noetig. min_deg/max_deg behalten ihren Spaltennamen, bedeuten
ab jetzt aber eine manuell einstellbare ABSOLUTE Ziel-Grenze (nach der
Kalibrierung angewendet, um den vollen Servo-Bereich bei Bedarf einzudaemmen)
statt einer Kandidatenwert-Begrenzung. scale/dead_zone_deg/zero_offset_deg
entfallen (durch die Zwei-Punkt-Kalibrierung ueberfluessig). Neu:
speed_percent (0-100) fuer eine pro-Gelenk einstellbare Bewegungsgeschwindigkeit.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("motion_capture_joint_mapping") as batch_op:
        batch_op.add_column(sa.Column("candidate_low_deg", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("candidate_high_deg", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "speed_percent", sa.Float(), nullable=False, server_default="100.0"
            )
        )
        batch_op.drop_column("scale")
        batch_op.drop_column("dead_zone_deg")
        batch_op.drop_column("zero_offset_deg")


def downgrade():
    with op.batch_alter_table("motion_capture_joint_mapping") as batch_op:
        batch_op.add_column(
            sa.Column("scale", sa.Float(), nullable=False, server_default="100.0")
        )
        batch_op.add_column(
            sa.Column("dead_zone_deg", sa.Float(), nullable=False, server_default="0.0")
        )
        batch_op.add_column(
            sa.Column(
                "zero_offset_deg", sa.Float(), nullable=False, server_default="0.0"
            )
        )
        batch_op.drop_column("speed_percent")
        batch_op.drop_column("candidate_high_deg")
        batch_op.drop_column("candidate_low_deg")
