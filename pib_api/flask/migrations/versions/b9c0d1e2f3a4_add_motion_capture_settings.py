"""add motion capture settings

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-07-17 00:00:00.000000

Legt die globale motion_capture_settings-Tabelle an (Singleton: id=1) fuer
die zwei Regler ueber der Motion-Capture-Tabelle:
- smoothing_alpha: EMA-Glaettungsfaktor der Motorziele (0-1, hoeher =
  direkter/schneller, niedriger = weicher/traeger). Wird vom
  gesture_control-ROS-Node gelesen.
- eval_max_hz: Deckel fuer die Auswertungsrate der Browser-Erkennung
  (MediaPipe), gegen Latenz-Rueckstau auf schwachen Geraeten.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "motion_capture_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "smoothing_alpha", sa.Float(), nullable=False, server_default="0.4"
        ),
        sa.Column(
            "eval_max_hz", sa.Float(), nullable=False, server_default="12.0"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT OR IGNORE INTO motion_capture_settings "
            "(id, smoothing_alpha, eval_max_hz) VALUES (1, 0.4, 12.0)"
        )
    )


def downgrade():
    op.drop_table("motion_capture_settings")
