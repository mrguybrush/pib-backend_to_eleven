from typing import Any, Optional, Tuple
from urllib.request import Request

from pib_api_client import send_request, URL_PREFIX

MOTION_CAPTURE_SETTINGS_URL = URL_PREFIX + "/gesture-control/settings"


def get_settings() -> Tuple[bool, Optional[dict[str, Any]]]:
    """Globale Motion-Capture-Regler (Singleton), z.B.
    {"smoothingAlpha": 0.4, "evalMaxHz": 12.0}."""
    request = Request(MOTION_CAPTURE_SETTINGS_URL, method="GET")
    successful, dto = send_request(request)
    if not successful or dto is None:
        return False, None
    return True, dto
