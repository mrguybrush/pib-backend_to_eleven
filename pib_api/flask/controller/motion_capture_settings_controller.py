from flask import Blueprint, request

from schema.motion_capture_settings_schema import motion_capture_settings_schema
from service import motion_capture_settings_service

bp = Blueprint("motion_capture_settings_controller", __name__)


@bp.route("", methods=["GET"])
def get_settings():
    settings = motion_capture_settings_service.get_settings()
    return motion_capture_settings_schema.dump(settings)


@bp.route("", methods=["PUT"])
def update_settings():
    settings_dto = motion_capture_settings_schema.load(request.json)
    settings = motion_capture_settings_service.update_settings(settings_dto)
    return motion_capture_settings_schema.dump(settings)
