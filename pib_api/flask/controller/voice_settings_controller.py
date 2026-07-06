from flask import Blueprint, request

from schema.voice_settings_schema import voice_settings_schema
from service import voice_settings_service

bp = Blueprint("voice_settings_controller", __name__)

# Liste der verfuegbaren deutschen Piper-Stimmen.
# "id" ist der Datei-Praefix (verweist auf ~/piper/voices/<id>/<id>.onnx),
# "visualName" ist der in der UI angezeigte Name,
# "gender" dient der UI-Gruppierung (m/w/neutral).
AVAILABLE_GERMAN_VOICES = [
    {"id": "de_DE-thorsten-low", "visualName": "Thorsten (schnell)", "gender": "male"},
    {"id": "de_DE-thorsten-medium", "visualName": "Thorsten (mittel)", "gender": "male"},
    {"id": "de_DE-thorsten-high", "visualName": "Thorsten (hohe Qualitaet)", "gender": "male"},
    {"id": "de_DE-thorsten_emotional-medium", "visualName": "Thorsten (emotional)", "gender": "male"},
    {"id": "de_DE-karlsson-low", "visualName": "Karlsson", "gender": "male"},
    {"id": "de_DE-pavoque-low", "visualName": "Pavoque", "gender": "male"},
    {"id": "de_DE-eva_k-x_low", "visualName": "Eva K.", "gender": "female"},
    {"id": "de_DE-kerstin-low", "visualName": "Kerstin", "gender": "female"},
    {"id": "de_DE-ramona-low", "visualName": "Ramona", "gender": "female"},
    {"id": "de_DE-mls-medium", "visualName": "MLS", "gender": "neutral"},
]


@bp.route("", methods=["GET"])
def get_voice_settings():
    settings = voice_settings_service.get_voice_settings()
    return voice_settings_schema.dump(settings)


@bp.route("", methods=["PUT"])
def update_voice_settings():
    voice_settings_dto = voice_settings_schema.load(request.json)
    settings = voice_settings_service.update_voice_settings(voice_settings_dto)
    return voice_settings_schema.dump(settings)


@bp.route("/available-voices", methods=["GET"])
def get_available_voices():
    return {"voices": AVAILABLE_GERMAN_VOICES}
