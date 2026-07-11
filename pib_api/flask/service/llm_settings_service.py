from typing import Any, Tuple
import requests
from model.llm_settings_model import LlmSettings
from app.app import db

# Feste ID der einzigen Einstellungs-Zeile (Singleton-Pattern).
_SETTINGS_ID = 1

_DEFAULT_LOCAL_LLM_URL = "http://host.docker.internal:11434/v1"
_DEFAULT_LOCAL_LLM_MODEL = "llama3.2"

# Lightweight endpoint just to check the key works - lists models instead of
# actually generating anything, so verifying costs nothing and needs no
# audio pipeline (unlike actually trying to talk to pib).
_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def get_llm_settings() -> LlmSettings:
    """
    Liefert die globale LLM-Settings-Zeile.
    Existiert sie noch nicht, wird sie mit Standardwerten angelegt.
    """
    settings = LlmSettings.query.filter_by(id=_SETTINGS_ID).first()
    if settings is None:
        settings = LlmSettings(
            id=_SETTINGS_ID,
            gemini_api_key=None,
            local_llm_url=_DEFAULT_LOCAL_LLM_URL,
            local_llm_model=_DEFAULT_LOCAL_LLM_MODEL,
        )
        db.session.add(settings)
        db.session.flush()
    return settings


def update_llm_settings(llm_settings_dto: Any) -> LlmSettings:
    """
    Aktualisiert die globale LLM-Settings-Zeile.
    Nur uebergebene Felder werden geaendert (partielles Update moeglich).
    """
    settings = get_llm_settings()
    if "gemini_api_key" in llm_settings_dto:
        settings.gemini_api_key = llm_settings_dto["gemini_api_key"]
    if "local_llm_url" in llm_settings_dto:
        settings.local_llm_url = llm_settings_dto["local_llm_url"]
    if "local_llm_model" in llm_settings_dto:
        settings.local_llm_model = llm_settings_dto["local_llm_model"]
    db.session.flush()
    return settings


def verify_gemini_key(api_key: str) -> Tuple[bool, str]:
    """Calls Google's models-list endpoint (cheap, side-effect-free) to
    check whether the key actually works. Needs internet access, same as
    the live-voice feature itself."""
    if not api_key or not api_key.strip():
        return False, "Kein API-Key eingegeben."
    try:
        response = requests.get(
            _GEMINI_MODELS_URL,
            params={"key": api_key.strip()},
            timeout=10,
        )
    except requests.RequestException as e:
        return False, f"Google konnte nicht erreicht werden: {e}"

    if response.status_code == 200:
        return True, "API-Key ist gültig."

    try:
        error_message = response.json().get("error", {}).get("message")
    except ValueError:
        error_message = None

    if response.status_code in (400, 401, 403):
        return False, error_message or "API-Key ist ungültig oder nicht freigeschaltet."
    return False, error_message or f"Unerwartete Antwort von Google (Status {response.status_code})."
