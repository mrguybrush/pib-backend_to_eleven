from flask import Blueprint, jsonify, request

from service import bricklet_pin_service

bp = Blueprint("bricklet_pin_controller", __name__)


@bp.route("", methods=["GET"])
def get_pin_grid():
    return jsonify(bricklet_pin_service.get_pin_grid())


@bp.route("/<int:bricklet_id>/<int:pin>", methods=["PATCH"])
def assign_pin(bricklet_id: int, pin: int):
    motor_name = (request.json or {}).get("motorName")
    try:
        bricklet_pin_service.assign_pin(bricklet_id, pin, motor_name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return "", 204


@bp.route("/<int:bricklet_id>/<int:pin>/defective", methods=["PATCH"])
def set_pin_defective(bricklet_id: int, pin: int):
    defective = bool((request.json or {}).get("defective"))
    try:
        bricklet_pin_service.set_pin_defective(bricklet_id, pin, defective)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return "", 204


@bp.route("/restart-motors", methods=["POST"])
def restart_motors():
    try:
        bricklet_pin_service.restart_motors_container()
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    return "", 204
