from app.app import db


class MotionCaptureSettings(db.Model):
    """
    Globale, roboterweite Regler fuer die Bewegungserfassung (genau eine
    Zeile, id=1). Werden ueber der Zuordnungstabelle auf der Motion-Capture-
    Seite eingestellt.

    - smoothing_alpha: EMA-Glaettungsfaktor der Motorziele (0-1). Hoeher =
      direkter/schneller, niedriger = weicher/traeger. Vom gesture_control-
      ROS-Node beim Start/Reload gelesen (gesture_capture._smooth).
    - eval_max_hz: Obergrenze der Erkennungsrate der Browser-MediaPipe-
      Auswertung, um Latenz-Rueckstau auf schwachen Geraeten zu vermeiden.
      Wird rein clientseitig angewendet (browser-pose-tracker.service).
    """

    __tablename__ = "motion_capture_settings"

    id = db.Column(db.Integer, primary_key=True)
    smoothing_alpha = db.Column(db.Float, nullable=False, default=0.4)
    eval_max_hz = db.Column(db.Float, nullable=False, default=12.0)
