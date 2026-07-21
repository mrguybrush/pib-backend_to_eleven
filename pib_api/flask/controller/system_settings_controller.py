from flask import Blueprint, jsonify, request

from service import system_settings_service

bp = Blueprint("system_settings_controller", __name__)


@bp.route("/auto-off", methods=["GET"])
def get_auto_off():
    return jsonify({"autoOffMinutes": system_settings_service.get_auto_off_minutes()})


@bp.route("/auto-off", methods=["PUT"])
def set_auto_off():
    minutes = (request.json or {}).get("autoOffMinutes")
    result = system_settings_service.set_auto_off_minutes(minutes)
    return jsonify({"autoOffMinutes": result})


@bp.route("/ip-overlay-seconds", methods=["GET"])
def get_ip_overlay_seconds():
    return jsonify(
        {"ipOverlaySeconds": system_settings_service.get_ip_overlay_seconds()}
    )


@bp.route("/ip-overlay-seconds", methods=["PUT"])
def set_ip_overlay_seconds():
    seconds = (request.json or {}).get("ipOverlaySeconds")
    result = system_settings_service.set_ip_overlay_seconds(seconds)
    return jsonify({"ipOverlaySeconds": result})


@bp.route("/menu-visibility", methods=["GET"])
def get_menu_visibility():
    return jsonify(system_settings_service.get_menu_visibility())


@bp.route("/menu-visibility", methods=["PUT"])
def set_menu_visibility():
    updates = request.json or {}
    result = system_settings_service.set_menu_visibility(updates)
    return jsonify(result)


@bp.route("/restart-display", methods=["POST"])
def restart_display():
    try:
        system_settings_service.restart_display_container()
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    return "", 204
