from typing import Any
from urllib.request import Request

from pib_api_client import send_request, URL_PREFIX

GESTURE_URL = URL_PREFIX + "/gesture-control/gestures/%s"


def get_motor_positions_of_gesture(gesture_id) -> tuple[bool, dict[str, Any] | None]:
    request = Request(GESTURE_URL % gesture_id, method="GET")
    successful, gesture = send_request(request)
    if not successful or gesture is None:
        return successful, None
    return True, {"motorPositions": gesture["motorPositions"]}
