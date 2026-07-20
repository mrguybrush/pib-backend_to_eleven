from typing import Optional, Tuple
from urllib.request import Request

from pib_api_client import send_request, URL_PREFIX

AUTO_OFF_URL = URL_PREFIX + "/system-settings/auto-off"


def get_auto_off_minutes() -> Tuple[bool, Optional[int]]:
    """Minuten ohne Bewegung, nach denen der Roboter automatisch in die
    Resting Pose faehrt und den Motorstrom abschaltet. None = deaktiviert."""
    request = Request(AUTO_OFF_URL, method="GET")
    successful, dto = send_request(request)
    if not successful or dto is None:
        return False, None
    return True, dto.get("autoOffMinutes")
