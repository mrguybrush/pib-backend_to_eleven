"""add auto_off_minutes to app_settings

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-11 00:00:00.000000

Ergaenzt app_settings.auto_off_minutes: Minuten ohne Bewegung, nach denen
der Roboter automatisch in die Resting Pose faehrt und den Motorstrom
abschaltet (verhindert Ueberhitzung). NULL = deaktiviert (Default).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.add_column(sa.Column("auto_off_minutes", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.drop_column("auto_off_minutes")
