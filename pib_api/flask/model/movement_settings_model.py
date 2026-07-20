from app.app import db


class MovementSettings(db.Model):
    """
    Globales Bewegungstempo, dem JEDE Bewegung folgt (manuelle
    Gelenksteuerung, Posen, Programme) - siehe pib_motors.motor.Motor.
    set_movement_speed_percent(). Skaliert dort die pro Motor konfigurierten
    velocity/acceleration/deceleration-Werte, ohne diese selbst zu
    veraendern.

    Diese Tabelle enthaelt genau eine Zeile (id=1).

    - speed_percent: 10-100, 100 = volle konfigurierte Geschwindigkeit jedes
      einzelnen Motors.
    - max_speed_percent: 10-100, obere Schranke (Sicherheits-Limit, in den
      System-Einstellungen gesetzt), die speed_percent nie ueberschreiten
      darf. Der Tempo-Regler unter Posen geht nur bis zu diesem Wert.
    """

    __tablename__ = "movement_settings"

    id = db.Column(db.Integer, primary_key=True)
    speed_percent = db.Column(db.Integer, nullable=False, default=100)
    max_speed_percent = db.Column(db.Integer, nullable=False, default=100)
