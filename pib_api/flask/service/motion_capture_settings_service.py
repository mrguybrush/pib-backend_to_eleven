from typing import Any
from model.motion_capture_settings_model import MotionCaptureSettings
from app.app import db

# Feste ID der einzigen Einstellungs-Zeile (Singleton-Pattern).
_SETTINGS_ID = 1


def get_settings() -> MotionCaptureSettings:
    """Liefert die globale Motion-Capture-Settings-Zeile; legt sie mit
    Standardwerten an, falls sie noch nicht existiert."""
    settings = MotionCaptureSettings.query.filter_by(id=_SETTINGS_ID).first()
    if settings is None:
        settings = MotionCaptureSettings(
            id=_SETTINGS_ID, smoothing_alpha=0.4, eval_max_hz=12.0
        )
        db.session.add(settings)
        db.session.flush()
    return settings


def update_settings(settings_dto: Any) -> MotionCaptureSettings:
    """Partielles Update - nur uebergebene Felder werden geaendert."""
    settings = get_settings()
    if "smoothing_alpha" in settings_dto:
        settings.smoothing_alpha = settings_dto["smoothing_alpha"]
    if "eval_max_hz" in settings_dto:
        settings.eval_max_hz = settings_dto["eval_max_hz"]
    db.session.flush()
    return settings
