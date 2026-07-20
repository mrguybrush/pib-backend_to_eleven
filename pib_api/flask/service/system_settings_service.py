from typing import Optional

from app.app import db
from model.learning_group_model import AppSettings
from service.container_control_service import restart_service_container

_SETTINGS_ID = 1

# Docker Compose service name (not container name) - see docker-compose.yaml.
ROS_DISPLAY_SERVICE_NAME = "ros-display"

# JSON-Key (Frontend) -> Spaltenname (AppSettings). True = ausgeblendet.
# Bezieht sich NUR auf die Hauptmenuepunkte der linken Navigationsleiste,
# nicht auf die Unterreiter innerhalb von System.
_MENU_VISIBILITY_FIELDS = {
    "jointControl": "hide_joint_control_nav",
    "pose": "hide_pose_nav",
    "camera": "hide_camera_nav",
    "motionCapture": "hide_motion_capture_nav",
    "voiceRecording": "hide_voice_recording_nav",
    "voiceAssistant": "hide_voice_assistant_nav",
    "program": "hide_program_nav",
    "system": "hide_system_nav",
}


def get_auto_off_minutes() -> Optional[int]:
    return _get_settings().auto_off_minutes


def set_auto_off_minutes(minutes: Optional[int]) -> Optional[int]:
    if minutes is not None and minutes <= 0:
        minutes = None  # 0/negativ = deaktiviert, konsistent mit NULL
    settings = _get_settings()
    settings.auto_off_minutes = minutes
    db.session.flush()
    return settings.auto_off_minutes


def get_menu_visibility() -> dict:
    settings = _get_settings()
    return {
        key: getattr(settings, column)
        for key, column in _MENU_VISIBILITY_FIELDS.items()
    }


def set_menu_visibility(updates: dict) -> dict:
    settings = _get_settings()
    for key, column in _MENU_VISIBILITY_FIELDS.items():
        if key in updates:
            setattr(settings, column, bool(updates[key]))
    db.session.flush()
    return get_menu_visibility()


def restart_display_container() -> None:
    """Restarts the ros-display container (Augen-Anzeige) - hilft, wenn die
    Augen nach dem Hochfahren nicht vollstaendig im Vollbild angezeigt
    werden."""
    restart_service_container(ROS_DISPLAY_SERVICE_NAME)


def _get_settings() -> AppSettings:
    settings = AppSettings.query.filter_by(id=_SETTINGS_ID).first()
    if settings is None:
        settings = AppSettings(id=_SETTINGS_ID, active_learning_group_id=None)
        db.session.add(settings)
        db.session.flush()
    return settings
