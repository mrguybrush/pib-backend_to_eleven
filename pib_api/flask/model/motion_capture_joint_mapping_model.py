from app.app import db


class MotionCaptureJointMapping(db.Model):
    """
    Pro-Installation-Override der Motion-Capture-Zuordnung (siehe
    gesture_control/retargeting.py): welche erkannte Koerperseite ("left"
    oder "right") welchen Robotermotor treibt, und ob das Vorzeichen
    invertiert werden muss.

    Eine Zeile pro Motor (motor_name eindeutig). Fehlt eine Zeile fuer einen
    Motor, wird der Default aus retargeting.DEFAULT_ASSIGNMENT verwendet
    (source_side = eigene Seite des Motornamens, invert = False) - das
    entspricht dem Verhalten vor Einfuehrung dieser Tabelle.

    Wird vom Kalibrierungs-Assistenten (Cerebra > Motion Capture) befuellt,
    damit Nutzer eine falsch geroutete Armbewegung selbst korrigieren
    koennen, statt auf eine feste Annahme angewiesen zu sein.
    """

    __tablename__ = "motion_capture_joint_mapping"

    id = db.Column(db.Integer, primary_key=True)
    motor_name = db.Column(db.String(255), nullable=False, unique=True)
    source_side = db.Column(db.String(10), nullable=False, default="left")
    invert = db.Column(db.Boolean, nullable=False, default=False)
