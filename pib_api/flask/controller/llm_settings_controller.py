from flask import Blueprint, jsonify, request

from schema.llm_settings_schema import llm_settings_schema
from service import llm_settings_service

bp = Blueprint("llm_settings_controller", __name__)


@bp.route("", methods=["GET"])
def get_llm_settings():
    settings = llm_settings_service.get_llm_settings()
    return llm_settings_schema.dump(settings)


@bp.route("", methods=["PUT"])
def update_llm_settings():
    llm_settings_dto = llm_settings_schema.load(request.json)
    settings = llm_settings_service.update_llm_settings(llm_settings_dto)
    return llm_settings_schema.dump(settings)


@bp.route("/verify-gemini-key", methods=["POST"])
def verify_gemini_key():
    """Tests a Gemini API key against Google's API without touching the
    voice-assistant's audio pipeline - lets the Settings page show an
    immediate yes/no instead of the user only finding out when they try to
    actually talk to pib."""
    api_key = (request.json or {}).get("geminiApiKey", "")
    valid, message = llm_settings_service.verify_gemini_key(api_key)
    return jsonify({"valid": valid, "message": message})
