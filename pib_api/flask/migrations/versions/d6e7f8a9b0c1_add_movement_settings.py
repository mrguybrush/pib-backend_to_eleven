"""add movement settings table

Revision ID: d6e7f8a9b0c1
Revises: c0d1e2f3a4b5
Create Date: 2026-07-18 00:00:00.000000

Legt die globale movement_settings-Tabelle an (Singleton: id=1) und
befuellt sie mit dem Standardwert (100% = volle konfigurierte
Geschwindigkeit jedes Motors).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d6e7f8a9b0c1"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "movement_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "speed_percent",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Standard-Zeile (id=1) einfuegen, damit immer genau eine Zeile existiert.
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            INSERT OR IGNORE INTO movement_settings (id, speed_percent)
            VALUES (1, 100)
        """)
    )


def downgrade():
    op.drop_table("movement_settings")
