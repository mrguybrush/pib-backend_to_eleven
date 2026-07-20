"""add movement access to personality

Revision ID: 78e8b0cfba96
Revises: 8409a82d3923
Create Date: 2026-07-20 00:00:00.000000

Erlaubt es, pro Personality festzulegen, ob der Gemini-Live-Sprachassistent
den move_joint-Funktionsaufruf nutzen und damit tatsaechlich Motoren bewegen
darf. Bestehende Personalities bekommen False (kein Verhaltenswechsel).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "78e8b0cfba96"
down_revision = "8409a82d3923"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("personality") as batch_op:
        batch_op.add_column(
            sa.Column(
                "movement_access_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("personality") as batch_op:
        batch_op.drop_column("movement_access_enabled")
