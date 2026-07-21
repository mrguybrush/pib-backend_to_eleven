"""add emotion access to personality

Revision ID: f8c4a8964459
Revises: 78e8b0cfba96
Create Date: 2026-07-21 00:00:00.000000

Erlaubt es, pro Personality festzulegen, ob der Gemini-Live-Sprachassistent
den show_emotion-Funktionsaufruf nutzen und damit passend zum Gespraech
Gesichtsausdruecke zeigen darf. Bestehende Personalities bekommen False
(kein Verhaltenswechsel).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f8c4a8964459"
down_revision = "78e8b0cfba96"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("personality") as batch_op:
        batch_op.add_column(
            sa.Column(
                "emotion_access_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("personality") as batch_op:
        batch_op.drop_column("emotion_access_enabled")
