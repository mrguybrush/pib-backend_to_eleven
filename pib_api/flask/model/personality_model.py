from app.app import db
from model.util import generate_uuid


class Personality(db.Model):

    __tablename__ = "personality"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    personality_id = db.Column(
        db.String(255), nullable=False, default=generate_uuid, unique=True
    )
    gender = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(38000), nullable=True)
    pause_threshold = db.Column(db.Float, nullable=False)
    message_history = db.Column(db.Integer, nullable=False)
    camera_access_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Erlaubt der Gemini-Live-Sprachsitzung, den move_joint-Funktionsaufruf zu
    # nutzen und damit tatsaechlich Motoren zu bewegen (siehe audio_loop.py
    # MOVE_JOINT_TOOL) - wie camera_access_enabled standardmaessig aus.
    movement_access_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Erlaubt der Gemini-Live-Sprachsitzung, den show_emotion-Funktionsaufruf
    # zu nutzen und damit passend zum Gespraech Gesichtsausdruecke auf pibs
    # Display zu zeigen (siehe audio_loop.py SHOW_EMOTION_TOOL) - eigener
    # Schalter, unabhaengig von movement_access_enabled.
    emotion_access_enabled = db.Column(db.Boolean, nullable=False, default=False)
    chats = db.relationship(
        "Chat", backref="personality", lazy=True, cascade="all,delete"
    )
    assistant_model_id = db.Column(
        db.Integer, db.ForeignKey("assistant_model.id"), nullable=False
    )
