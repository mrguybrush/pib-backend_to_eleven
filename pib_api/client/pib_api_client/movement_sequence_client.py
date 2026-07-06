from typing import Any
from urllib.request import Request

from pib_api_client import send_request, URL_PREFIX

MOVEMENT_SEQUENCE_URL = URL_PREFIX + "/gesture-control/sequences/%s"


def get_frames_of_movement_sequence(sequence_id) -> tuple[bool, dict[str, Any] | None]:
    request = Request(MOVEMENT_SEQUENCE_URL % sequence_id, method="GET")
    successful, sequence = send_request(request)
    if not successful or sequence is None:
        return successful, None
    return True, {"frames": sequence["frames"]}
