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
    # Zwei-Punkt-Kalibrierung (siehe retargeting.JointAssignment): die rohen
    # Kamera-Ablesungen bei Gelenk "unten"/"oben" (per "Ist-Wert"-Button in
    # der Tabelle gesetzt) werden linear auf die volle physische Spanne des
    # Servos (motor.rotation_range_min/max) abgebildet. NULL = noch nicht
    # kalibriert, Code-Default aus retargeting.DEFAULT_ASSIGNMENT gilt.
    candidate_low_deg = db.Column(db.Float, nullable=True)
    candidate_high_deg = db.Column(db.Float, nullable=True)
    # Manuelle ABSOLUTE Ziel-Grenze (Motor-Grad, nach der Kalibrierung
    # angewendet) - um den vollen Servo-Bereich bei Bedarf einzudaemmen.
    # NULL = keine zusaetzliche Begrenzung (voller Servo-Bereich gilt).
    min_deg = db.Column(db.Float, nullable=True)
    max_deg = db.Column(db.Float, nullable=True)
    # Bewegungsgeschwindigkeit dieses Gelenks in Prozent (0-100) des
    # globalen Tempolimits (siehe gesture_capture.MAX_STEP_PER_TICK).
    speed_percent = db.Column(db.Float, nullable=False, default=100.0)
