from typing import Any
from model.voice_settings_model import VoiceSettings
from app.app import db

# Feste ID der einzigen Einstellungs-Zeile (Singleton-Pattern).
_SETTINGS_ID = 1


def get_voice_settings() -> VoiceSettings:
    """
    Liefert die globale Voice-Settings-Zeile.
    Existiert sie noch nicht, wird sie mit Standardwerten angelegt.
    """
    settings = VoiceSettings.query.filter_by(id=_SETTINGS_ID).first()
    if settings is None:
        settings = VoiceSettings(
            id=_SETTINGS_ID,
            local_voice_enabled=False,
            local_voice_model="de_DE-thorsten-low",
        )
        db.session.add(settings)
        db.session.flush()
    return settings


def update_voice_settings(voice_settings_dto: Any) -> VoiceSettings:
    """
    Aktualisiert die globale Voice-Settings-Zeile.
    Nur uebergebene Felder werden geaendert (partielles Update moeglich).
    """
    settings = get_voice_settings()
    if "local_voice_enabled" in voice_settings_dto:
        settings.local_voice_enabled = voice_settings_dto["local_voice_enabled"]
    if "local_voice_model" in voice_settings_dto:
        settings.local_voice_model = voice_settings_dto["local_voice_model"]
    db.session.flush()
    return settings
