"""add defective_pin table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-11 00:00:00.000000

Legt die defective_pin-Tabelle an: markiert einen physischen (Bricklet,
Pin)-Steckplatz als defekt (z.B. durchgebrannt), unabhaengig davon, ob
gerade ein Motor dort angeschlossen ist - fuer die neue Pinbelegungs-Seite.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "defective_pin",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bricklet_id", sa.Integer(), nullable=False),
        sa.Column("pin", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["bricklet_id"], ["bricklet.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bricklet_id", "pin"),
    )


def downgrade():
    op.drop_table("defective_pin")
