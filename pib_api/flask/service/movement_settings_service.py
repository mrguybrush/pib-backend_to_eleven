from typing import Any
from model.movement_settings_model import MovementSettings
from app.app import db

# Feste ID der einzigen Einstellungs-Zeile (Singleton-Pattern).
_SETTINGS_ID = 1

MIN_SPEED_PERCENT = 10
# 100 = die normale, in den Motor-Einstellungen konfigurierte Geschwindigkeit
# jedes Motors - bleibt der DEFAULT fuer eine frische Installation.
DEFAULT_SPEED_PERCENT = 100
# Absolute Obergrenze, bis zu der die Maximalgeschwindigkeit in den System-
# Einstellungen hochgesetzt werden darf (>100% faehrt Motoren schneller als
# ihre eigentlich konfigurierte "normale" Geschwindigkeit).
MAX_SPEED_PERCENT = 150


def get_movement_settings() -> MovementSettings:
    """
    Liefert die globale Movement-Settings-Zeile.
    Existiert sie noch nicht, wird sie mit Standardwerten angelegt.
    """
    settings = MovementSettings.query.filter_by(id=_SETTINGS_ID).first()
    if settings is None:
        settings = MovementSettings(
            id=_SETTINGS_ID,
            speed_percent=DEFAULT_SPEED_PERCENT,
            max_speed_percent=DEFAULT_SPEED_PERCENT,
        )
        db.session.add(settings)
        db.session.flush()
    return settings


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def update_movement_settings(movement_settings_dto: Any) -> MovementSettings:
    """
    Aktualisiert die globale Movement-Settings-Zeile.

    max_speed_percent (Sicherheits-Obergrenze) wird zuerst uebernommen, dann
    speed_percent auf [MIN_SPEED_PERCENT, max_speed_percent] begrenzt. Wird
    das Maximum gesenkt, zieht das ein zu hohes aktuelles Tempo automatisch
    mit nach unten - so kann der Regler nie ueber dem Limit stehen.
    """
    settings = get_movement_settings()

    if "max_speed_percent" in movement_settings_dto:
        settings.max_speed_percent = _clamp(
            movement_settings_dto["max_speed_percent"],
            MIN_SPEED_PERCENT,
            MAX_SPEED_PERCENT,
        )

    if "speed_percent" in movement_settings_dto:
        settings.speed_percent = _clamp(
            movement_settings_dto["speed_percent"],
            MIN_SPEED_PERCENT,
            settings.max_speed_percent,
        )

    # Falls das (evtl. neue) Maximum unter dem aktuellen Tempo liegt, Tempo
    # nachziehen - auch wenn in diesem Request kein speed_percent kam.
    if settings.speed_percent > settings.max_speed_percent:
        settings.speed_percent = settings.max_speed_percent

    db.session.flush()
    return settings
