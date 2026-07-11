"""add llm settings table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-07 00:00:00.000000

Legt die globale llm_settings-Tabelle an (Singleton: id=1) fuer
Verbindungsdaten von Chat-LLMs ohne tryb-Token: Gemini-API-Key und die
Adresse/Modell eines LLM im lokalen Netzwerk.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "llm_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gemini_api_key", sa.String(length=255), nullable=True),
        sa.Column(
            "local_llm_url",
            sa.String(length=255),
            nullable=False,
            server_default="http://host.docker.internal:11434/v1",
        ),
        sa.Column(
            "local_llm_model",
            sa.String(length=255),
            nullable=False,
            server_default="llama3.2",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text("""
            INSERT OR IGNORE INTO llm_settings (id, gemini_api_key, local_llm_url, local_llm_model)
            VALUES (1, NULL, 'http://host.docker.internal:11434/v1', 'llama3.2')
        """)
    )


def downgrade():
    op.drop_table("llm_settings")
