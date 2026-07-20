from typing import Any, Optional, Tuple
from urllib.request import Request
import json

from pib_api_client import send_request, URL_PREFIX

MOVEMENT_SETTINGS_URL = URL_PREFIX + "/movement-settings"


def get_settings() -> Tuple[bool, Optional[dict[str, Any]]]:
    """Globales Bewegungstempo (Singleton), z.B. {"speedPercent": 100}."""
    request = Request(MOVEMENT_SETTINGS_URL, method="GET")
    return send_request(request)


def update_settings(
    movement_settings_dto: dict[str, Any],
) -> Tuple[bool, Optional[dict[str, Any]]]:
    request = Request(
        MOVEMENT_SETTINGS_URL,
        method="PUT",
        headers={"Content-Type": "application/json"},
        data=json.dumps(movement_settings_dto).encode("UTF-8"),
    )
    return send_request(request)
