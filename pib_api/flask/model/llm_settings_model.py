from app.app import db


class LlmSettings(db.Model):
    """
    Globale, roboterweite Verbindungsdaten fuer Chat-LLMs, die keinen
    tryb-Smart-API-Token brauchen: Gemini (eigener API-Key) und ein LLM im
    lokalen Netzwerk (OpenAI-kompatible API, z.B. Ollama).

    Diese Tabelle enthaelt genau eine Zeile (id=1), analog zu VoiceSettings.
    Ersetzt die reine docker-compose-Konfiguration (LOCAL_LLM_URL/MODEL) als
    Default, damit alles im Frontend (Einstellungen) eingetragen werden kann.
    """

    __tablename__ = "llm_settings"

    id = db.Column(db.Integer, primary_key=True)
    gemini_api_key = db.Column(db.String(255), nullable=True)
    local_llm_url = db.Column(
        db.String(255), nullable=False, default="http://host.docker.internal:11434/v1"
    )
    local_llm_model = db.Column(db.String(255), nullable=False, default="llama3.2")
