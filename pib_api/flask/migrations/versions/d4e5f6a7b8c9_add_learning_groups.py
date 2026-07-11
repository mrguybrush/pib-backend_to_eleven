"""add learning groups

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-09 00:00:00.000000

Lerngruppen: Programme und Posen koennen einer Gruppe zugeordnet werden;
die in den Einstellungen gewaehlte aktive Gruppe (app_settings, Singleton)
filtert die Listen-Endpoints. Bestehende Eintraege bleiben ohne Gruppe
(learning_group_id NULL) und sind sichtbar, solange keine Gruppe aktiv ist.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "learning_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active_learning_group_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["active_learning_group_id"], ["learning_group.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT OR IGNORE INTO app_settings (id, active_learning_group_id) VALUES (1, NULL)"
        )
    )

    # batch mode: SQLite can't ALTER TABLE ADD CONSTRAINT directly
    with op.batch_alter_table("program") as batch_op:
        batch_op.add_column(
            sa.Column("learning_group_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_program_learning_group", "learning_group", ["learning_group_id"], ["id"]
        )
    with op.batch_alter_table("pose") as batch_op:
        batch_op.add_column(
            sa.Column("learning_group_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_pose_learning_group", "learning_group", ["learning_group_id"], ["id"]
        )


def downgrade():
    with op.batch_alter_table("pose") as batch_op:
        batch_op.drop_constraint("fk_pose_learning_group", type_="foreignkey")
        batch_op.drop_column("learning_group_id")
    with op.batch_alter_table("program") as batch_op:
        batch_op.drop_constraint("fk_program_learning_group", type_="foreignkey")
        batch_op.drop_column("learning_group_id")
    op.drop_table("app_settings")
    op.drop_table("learning_group")
