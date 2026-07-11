from app.app import db
from model.util import generate_uuid


class LearningGroup(db.Model):
    """
    Eine Lerngruppe (z.B. eine Schulklasse oder ein Kurs): Programme und
    Posen koennen einer Gruppe zugeordnet sein. Ist in den Einstellungen
    eine Gruppe als aktiv gewaehlt (AppSettings.active_learning_group_id),
    zeigen die Listen-Endpoints nur noch deren Inhalte an - plus die
    nicht-loeschbaren Standard-Posen (Startup/Resting), die immer sichtbar
    bleiben.
    """

    __tablename__ = "learning_group"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(
        db.String(255), nullable=False, default=generate_uuid, unique=True
    )
    name = db.Column(db.String(255), nullable=False, unique=True)


class AppSettings(db.Model):
    """
    Globale App-Einstellungen (Singleton, id=1) - aktuell nur die aktive
    Lerngruppe. Analog zu VoiceSettings/LlmSettings als eigene
    Einzeiler-Tabelle gehalten.
    """

    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    active_learning_group_id = db.Column(
        db.Integer, db.ForeignKey("learning_group.id"), nullable=True
    )
