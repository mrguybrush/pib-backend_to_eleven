"""add camera access to personality

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-10 00:00:00.000000

Erlaubt es, pro Personality festzulegen, ob der Gemini-Live-Sprachassistent
waehrend eines laufenden Gespraechs periodisch Kamerabilder mitsenden darf.
Bestehende Personalities bekommen False (kein Verhaltenswechsel).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("personality") as batch_op:
        batch_op.add_column(
            sa.Column(
                "camera_access_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("personality") as batch_op:
        batch_op.drop_column("camera_access_enabled")
