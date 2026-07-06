from service import gesture_service
from schema.gesture_schema import (
    gestures_schema,
    gesture_schema,
    create_gesture_schema,
    gesture_schema_name_only,
)
from flask import jsonify, request, Blueprint

bp = Blueprint("gesture_controller", __name__)


@bp.route("", methods=["POST"])
def create_gesture():
    gesture_dto = create_gesture_schema.load(request.json)
    gesture = gesture_service.create_gesture(gesture_dto)
    return gesture_schema.dump(gesture), 201


@bp.route("", methods=["GET"])
def get_all_gestures():
    gestures = gesture_service.get_all_gestures()
    return jsonify({"gestures": gestures_schema.dump(gestures)})


@bp.route("/<string:gesture_id>", methods=["GET"])
def get_gesture(gesture_id: str):
    gesture = gesture_service.get_gesture(gesture_id)
    return gesture_schema.dump(gesture)


@bp.route("/<string:gesture_id>", methods=["DELETE"])
def delete_gesture(gesture_id: str):
    gesture_service.delete_gesture(gesture_id)
    return "", 204


@bp.route("/<string:gesture_id>", methods=["PATCH"])
def rename_gesture(gesture_id: str):
    gesture_dto = gesture_schema_name_only.load(request.json)
    gesture = gesture_service.rename_gesture(gesture_id, gesture_dto)
    return gesture_schema.dump(gesture)
