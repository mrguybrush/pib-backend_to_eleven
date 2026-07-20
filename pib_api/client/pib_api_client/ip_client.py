from typing import Optional, Tuple
from urllib.request import Request

from pib_api_client import send_request, URL_PREFIX

HOST_IP_URL = URL_PREFIX + "/host-ip"


def get_host_ip() -> Tuple[bool, Optional[str]]:
    request = Request(HOST_IP_URL, method="GET")
    successful, dto = send_request(request)
    if not successful or dto is None:
        return False, None
    return True, dto.get("host_ip")
