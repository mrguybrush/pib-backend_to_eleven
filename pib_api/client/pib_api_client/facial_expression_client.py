from typing import Any
from urllib.request import Request

from pib_api_client import send_request, URL_PREFIX

FACIAL_EXPRESSIONS_URL = URL_PREFIX + "/facial-expressions"


def get_all_facial_expressions() -> tuple[bool, dict[str, Any] | None]:
    request = Request(FACIAL_EXPRESSIONS_URL, method="GET")
    return send_request(request)
