"""add facial_expression table

Revision ID: a1b2c3d4e5f6
Revises: e7f8a9b0c1d2
Create Date: 2026-07-20 00:00:00.000000

Legt die facial_expression-Tabelle an: benutzerdefinierte Gesichtsausdruecke
(Name + zugehoerige, auf der Platte unter FACIAL_EXPRESSIONS_DIR liegende
GIF-Datei "<expression_id>.gif" + Drag&Drop-Sortierreihenfolge).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "8409a82d3923"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "facial_expression",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("expression_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sort_index", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("expression_id"),
        sa.UniqueConstraint("name"),
    )


def downgrade():
    op.drop_table("facial_expression")
