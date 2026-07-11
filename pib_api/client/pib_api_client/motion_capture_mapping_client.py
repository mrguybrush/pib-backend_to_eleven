from typing import Any, List, Tuple
from urllib.request import Request

from pib_api_client import send_request, URL_PREFIX

JOINT_MAPPING_URL = URL_PREFIX + "/gesture-control/joint-mapping"


def get_joint_mapping() -> Tuple[bool, List[dict[str, Any]]]:
    """Pro-Installation-Override von retargeting.DEFAULT_ASSIGNMENT, wie im
    Kalibrierungs-Assistenten (Cerebra > Motion Capture) hinterlegt.
    Liste von {"motorName": str, "sourceSide": "left"|"right", "invert": bool}.
    """
    request = Request(JOINT_MAPPING_URL, method="GET")
    successful, dto = send_request(request)
    if not successful or dto is None:
        return False, []
    return True, dto.get("mappings", [])
