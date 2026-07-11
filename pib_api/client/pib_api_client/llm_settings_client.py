from typing import Any, Tuple
from urllib.request import Request

from pib_api_client import send_request, URL_PREFIX

LLM_SETTINGS_URL = URL_PREFIX + "/voice-assistant/llm-settings"


def get_llm_settings() -> Tuple[bool, dict[str, Any]]:
    """Gemini-API-Key + Adresse/Modell des lokalen Netzwerk-LLM, wie im
    Frontend unter Einstellungen hinterlegt."""
    request = Request(LLM_SETTINGS_URL, method="GET")
    return send_request(request)
