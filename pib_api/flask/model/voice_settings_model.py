from app.app import db


class VoiceSettings(db.Model):
    """
    Globale, roboterweite Einstellungen fuer die Sprachausgabe (TTS).

    Diese Tabelle enthaelt genau eine Zeile (id=1). Sie steuert, ob die
    lokale Piper-Sprachsynthese verwendet wird (statt der Cloud/Public-API)
    und welche deutsche Piper-Stimme dabei zum Einsatz kommt.

    - local_voice_enabled: Wenn True, wird die Sprachausgabe lokal ueber
      Piper erzeugt, unabhaengig davon, welches LLM (auch Cloud) verbunden ist.
    - local_voice_model: Der Dateiname-Praefix des Piper-Modells,
      z.B. "de_DE-thorsten-low". Verweist auf
      ~/piper/voices/<name>/<name>.onnx
    """

    __tablename__ = "voice_settings"

    id = db.Column(db.Integer, primary_key=True)
    local_voice_enabled = db.Column(db.Boolean, nullable=False, default=False)
    local_voice_model = db.Column(
        db.String(255), nullable=False, default="de_DE-thorsten-low"
    )
