import json
from typing import Any, Tuple, List
from urllib.request import Request

from pib_api_client import send_request, URL_PREFIX

ASSISTANT_MODEL_URL = URL_PREFIX + "/assistant-model/%s"
PERSONALITY_URL = URL_PREFIX + "/voice-assistant/personality/%s"
CHAT_URL = URL_PREFIX + "/voice-assistant/chat/%s"
ALL_CHATS_URL = URL_PREFIX + "/voice-assistant/chat"
CHAT_MESSAGES_URL = URL_PREFIX + "/voice-assistant/chat/%s/messages"
VOICE_SETTINGS_URL = URL_PREFIX + "/voice-assistant/voice-settings"


class AssistantModel:
    def __init__(self, assistant_dto: dict[str, Any]):
        self.model_id = assistant_dto["id"]
        self.api_name = assistant_dto["apiName"]
        self.visual_name = assistant_dto["visualName"]
        self.has_image_support = assistant_dto["hasImageSupport"]


class Personality:
    def __init__(self, personality_dto: dict[str, Any]):
        self.gender = personality_dto["gender"]
        self.language = "German"  # TODO: language should be stored as part of a personality -> personality_dto["language"]
        self.pause_threshold = personality_dto["pauseThreshold"]
        self.message_history = personality_dto["messageHistory"]
        self.description = personality_dto.get("description")
        self.camera_access_enabled = personality_dto.get(
            "cameraAccessEnabled", False
        )
        self.assistant_model = self._get_assistant_model(
            personality_dto["assistantModelId"]
        )

    def _get_assistant_model(self, assistant_model_id: int) -> AssistantModel:
        successful, model = get_assistant_model(assistant_model_id)
        if not successful:
            raise Exception("Could not find the assistant model")
        return model


class VoiceSettings:
    """Globale TTS-Einstellungen (lokale Piper-Stimme an/aus + gewaehlte Stimme)."""

    def __init__(self, voice_settings_dto: dict[str, Any]):
        self.local_voice_enabled = voice_settings_dto["localVoiceEnabled"]
        self.local_voice_model = voice_settings_dto["localVoiceModel"]


class Chat:

    def __init__(self, chat_dto: dict[str, Any]):
        self.chatId = chat_dto["chatId"]
        self.topic = chat_dto["topic"]
        self.personality_id = chat_dto["personalityId"]


class ChatMessage:

    def __init__(self, chat_message_dto: dict[str, Any]):
        self.message_id = chat_message_dto["messageId"]
        self.timestamp = chat_message_dto["timestamp"]
        self.is_user = chat_message_dto["isUser"]
        self.content = chat_message_dto["content"]


def get_assistant_model(assistant_model_id: int) -> Tuple[bool, AssistantModel]:
    request = Request(ASSISTANT_MODEL_URL % assistant_model_id, method="GET")
    successful, assistant_model_dto = send_request(request)
    return successful, AssistantModel(assistant_model_dto)


def get_personality(personality_id: str) -> Tuple[bool, Personality]:
    request = Request(PERSONALITY_URL % personality_id, method="GET")
    successful, personality_dto = send_request(request)
    try:
        personality = Personality(personality_dto)
    except Exception:
        successful = False
        personality = None
    return successful, personality


def get_chat(chat_id: str) -> Tuple[bool, Chat]:
    request = Request(CHAT_URL % chat_id, method="GET")
    successful, chat_dto = send_request(request)
    return successful, Chat(chat_dto)


def get_all_chats() -> Tuple[bool, List[Chat]]:
    request = Request(ALL_CHATS_URL, method="GET")
    successful, dto = send_request(request)
    if not successful or dto is None:
        return False, []
    return True, [Chat(chat_dto) for chat_dto in dto.get("voiceAssistantChats", [])]


def get_personality_from_chat(chat_id: str) -> Tuple[bool, Personality]:
    successful, chat = get_chat(chat_id)
    if not successful:
        return False, None
    return get_personality(chat.personality_id)


def create_chat_message(
    chat_id: str, message_content: str, is_user: bool
) -> Tuple[bool, ChatMessage]:
    data = json.dumps({"isUser": is_user, "content": message_content}).encode("UTF-8")
    request = Request(
        CHAT_MESSAGES_URL % chat_id,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=data,
    )
    successful, chat_message_dto = send_request(request)
    return successful, ChatMessage(chat_message_dto)


def update_chat_message(
    chat_id: str, message_content: str, is_user: bool, message_id: str
) -> Tuple[bool, ChatMessage]:
    data = json.dumps({"isUser": is_user, "content": message_content}).encode("UTF-8")
    request = Request(
        CHAT_MESSAGES_URL % chat_id + "/" + message_id,
        method="PUT",
        headers={"Content-Type": "application/json"},
        data=data,
    )
    successful, chat_message_dto = send_request(request)
    return successful, ChatMessage(chat_message_dto)


def get_voice_settings() -> Tuple[bool, "VoiceSettings"]:
    """Holt die globalen TTS-Einstellungen vom pib-API."""
    request = Request(VOICE_SETTINGS_URL, method="GET")
    successful, voice_settings_dto = send_request(request)
    if not successful:
        return False, None
    try:
        voice_settings = VoiceSettings(voice_settings_dto)
    except Exception:
        return False, None
    return True, voice_settings


def get_all_chat_messages(chat_id: str) -> List[ChatMessage]:
    request = Request(CHAT_MESSAGES_URL % chat_id, method="GET")
    successful, chat_messages_dto = send_request(request)
    if not successful:
        return successful, None
    chat_message_dtos = chat_messages_dto["messages"]
    chat_messages = [
        ChatMessage(chat_message_dto) for chat_message_dto in chat_message_dtos
    ]
    return successful, chat_messages


def get_chat_history(chat_id: str, history_length: int) -> List[ChatMessage]:
    request = Request(
        CHAT_MESSAGES_URL % chat_id + f"/{history_length}",
        method="GET",
    )
    successful, chat_messages_dto = send_request(request)
    if not successful:
        return successful, None
    chat_message_dtos = chat_messages_dto["messages"]
    chat_messages = [
        ChatMessage(chat_message_dto) for chat_message_dto in chat_message_dtos
    ]
    return successful, chat_messages
