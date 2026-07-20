"""pose sort order + hide experimental motion capture

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-07-17 00:00:00.000000

1. pose.sort_index (nullable): Drag&Drop-Sortierung der Posen-Liste. NULL =
   noch nie einsortiert, faellt ans Listenende (coalesce in pose_service).
2. Bewegungserfassung ist als EXPERIMENTELL markiert und wird per Default im
   Hauptmenue ausgeblendet (hide_motion_capture_nav=1, auch fuer bestehende
   Installationen) - wieder einschaltbar unter Einstellungen > Menuepunkte.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pose") as batch_op:
        batch_op.add_column(sa.Column("sort_index", sa.Integer(), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("UPDATE app_settings SET hide_motion_capture_nav = 1"))


def downgrade():
    with op.batch_alter_table("pose") as batch_op:
        batch_op.drop_column("sort_index")
