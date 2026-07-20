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
    Globale App-Einstellungen (Singleton, id=1) - aktive Lerngruppe und
    Auto-Off-Zeit. Analog zu VoiceSettings/LlmSettings als eigene
    Einzeiler-Tabelle gehalten.
    """

    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    active_learning_group_id = db.Column(
        db.Integer, db.ForeignKey("learning_group.id"), nullable=True
    )
    # Minuten ohne Bewegung, nach denen der Roboter automatisch in die
    # Resting Pose faehrt und den Motorstrom abschaltet. NULL = deaktiviert.
    auto_off_minutes = db.Column(db.Integer, nullable=True)

    # Sichtbarkeit der Hauptmenuepunkte in der linken Navigation (True =
    # ausgeblendet). Ausgeblendete Seiten bleiben ueber die direkte URL
    # erreichbar, es fehlt nur der Link.
    hide_joint_control_nav = db.Column(db.Boolean, nullable=False, default=False)
    hide_pose_nav = db.Column(db.Boolean, nullable=False, default=False)
    hide_camera_nav = db.Column(db.Boolean, nullable=False, default=False)
    # Bewegungserfassung ist experimentell und per Default ausgeblendet -
    # einschaltbar unter Einstellungen > Menuepunkte.
    hide_motion_capture_nav = db.Column(db.Boolean, nullable=False, default=True)
    hide_voice_recording_nav = db.Column(db.Boolean, nullable=False, default=False)
    hide_voice_assistant_nav = db.Column(db.Boolean, nullable=False, default=False)
    hide_program_nav = db.Column(db.Boolean, nullable=False, default=False)
    hide_system_nav = db.Column(db.Boolean, nullable=False, default=False)
