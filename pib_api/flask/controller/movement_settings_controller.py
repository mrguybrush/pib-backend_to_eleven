from flask import Blueprint, request

from schema.movement_settings_schema import movement_settings_schema
from service import movement_settings_service

bp = Blueprint("movement_settings_controller", __name__)


@bp.route("", methods=["GET"])
def get_movement_settings():
    settings = movement_settings_service.get_movement_settings()
    return movement_settings_schema.dump(settings)


@bp.route("", methods=["PUT"])
def update_movement_settings():
    movement_settings_dto = movement_settings_schema.load(request.json)
    settings = movement_settings_service.update_movement_settings(
        movement_settings_dto
    )
    return movement_settings_schema.dump(settings)
