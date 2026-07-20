"""restrict menu visibility flags to the main navigation items

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-14 01:00:00.000000

Die vorige Migration blendete die System-Unterreiter (Einstellungen,
Zuordnungen, Pinbelegung, Hardware-IDs) aus - gemeint waren aber nur die
Hauptmenuepunkte der linken Navigationsleiste. Ersetzt die 4
Unterreiter-Spalten durch je eine Spalte pro Hauptmenuepunkt.
hide_system_nav bleibt unveraendert bestehen.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None

_NEW_COLUMNS = [
    "hide_joint_control_nav",
    "hide_pose_nav",
    "hide_camera_nav",
    "hide_motion_capture_nav",
    "hide_voice_recording_nav",
    "hide_voice_assistant_nav",
    "hide_program_nav",
]

_DROPPED_COLUMNS = [
    "hide_settings_menu",
    "hide_program_assignment_menu",
    "hide_pin_assignment_menu",
    "hide_hardware_ids_menu",
]


def upgrade():
    with op.batch_alter_table("app_settings") as batch_op:
        for column in _NEW_COLUMNS:
            batch_op.add_column(
                sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false())
            )
        for column in _DROPPED_COLUMNS:
            batch_op.drop_column(column)


def downgrade():
    with op.batch_alter_table("app_settings") as batch_op:
        for column in _DROPPED_COLUMNS:
            batch_op.add_column(
                sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false())
            )
        for column in _NEW_COLUMNS:
            batch_op.drop_column(column)
