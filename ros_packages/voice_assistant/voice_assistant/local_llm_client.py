"""
Client for a local-network LLM with an OpenAI-compatible chat API
(e.g. Ollama, LM Studio, llama.cpp server, vLLM).

Selected via the assistant-model "local-llm" (visual name
"Lokales Netzwerk-LLM") in the personality settings. Needs no tryb token
and no internet - only the endpoint, which the caller reads from the
llm_settings table (configurable under Cerebra > System > Einstellungen)
and passes in. LOCAL_LLM_URL/LOCAL_LLM_MODEL env vars are only the
fallback default for that DB row (see llm_settings_service.py) and for
callers that don't look the settings up themselves.

Streaming uses the standard OpenAI SSE format ("data: {...}" lines,
terminated by "data: [DONE]"), which all the servers above speak.
"""
import json
import os
from typing import Iterable, Optional

import requests

LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://host.docker.internal:11434/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3.2")

REQUEST_TIMEOUT_SECONDS = 120

# marker used in the assistant_model table's api_name column
API_NAME = "local-llm"


def is_local_llm(api_name: str) -> bool:
    return api_name.strip().lower() == API_NAME


def chat_completion(
    text: str,
    description: str,
    message_history: list,
    image_base64: Optional[str] = None,
    url: Optional[str] = None,
    model: Optional[str] = None,
) -> Iterable[str]:
    """Streams response tokens for the given prompt from the local LLM.
    `message_history` items need `content` and `is_user` attributes
    (same shape as public_voice_client.PublicApiChatMessage). `url`/`model`
    override the env-var defaults - callers should pass the values from
    llm_settings_client.get_llm_settings()."""
    url = url or LOCAL_LLM_URL
    model = model or LOCAL_LLM_MODEL

    messages = [{"role": "system", "content": description}]
    for message in message_history:
        role = "user" if message.is_user else "assistant"
        messages.append({"role": role, "content": message.content})
    if image_base64:
        # OpenAI-style multimodal content; servers without vision support
        # simply reject or ignore this - has_image_support should be off
        # for the local model unless the server can handle it.
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        },
                    },
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": text})

    response = requests.post(
        f"{url.rstrip('/')}/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "stream": True,
        },
        stream=True,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    response.encoding = "utf-8"

    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            break
        try:
            delta = json.loads(payload)["choices"][0]["delta"]
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
        token = delta.get("content")
        if token:
            yield token
