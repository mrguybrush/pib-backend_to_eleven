"""add voice settings table

Revision ID: f1a2b3c4d5e6
Revises: d4d024ef3a32
Create Date: 2026-07-01 00:00:00.000000

Legt die globale voice_settings-Tabelle an (Singleton: id=1) und befuellt
sie mit Standardwerten (lokale Stimme aus, Standardstimme Thorsten low).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "d4d024ef3a32"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "voice_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "local_voice_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "local_voice_model",
            sa.String(length=255),
            nullable=False,
            server_default="de_DE-thorsten-low",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Standard-Zeile (id=1) einfuegen, damit immer genau eine Zeile existiert.
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            INSERT OR IGNORE INTO voice_settings (id, local_voice_enabled, local_voice_model)
            VALUES (1, false, 'de_DE-thorsten-low')
        """)
    )


def downgrade():
    op.drop_table("voice_settings")
