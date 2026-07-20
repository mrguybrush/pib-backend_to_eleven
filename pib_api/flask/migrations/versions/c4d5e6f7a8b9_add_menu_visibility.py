"""add menu visibility flags to app_settings

Revision ID: c4d5e6f7a8b9
Revises: a7b8c9d0e1f2
Create Date: 2026-07-14 00:00:00.000000

Ergaenzt app_settings um Sichtbarkeits-Flags fuer die System-Menuepunkte
(Einstellungen, Zuordnungen, Pinbelegung, Hardware-IDs) sowie fuer den
"System"-Eintrag der Hauptnavigation selbst. True = ausgeblendet (Default
False = sichtbar). Ausgeblendete Seiten bleiben ueber die direkte URL
weiterhin erreichbar, es fehlt nur der Menuepunkt.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b9"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "hide_system_nav",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "hide_settings_menu",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "hide_program_assignment_menu",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "hide_pin_assignment_menu",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "hide_hardware_ids_menu",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.drop_column("hide_hardware_ids_menu")
        batch_op.drop_column("hide_pin_assignment_menu")
        batch_op.drop_column("hide_program_assignment_menu")
        batch_op.drop_column("hide_settings_menu")
        batch_op.drop_column("hide_system_nav")
