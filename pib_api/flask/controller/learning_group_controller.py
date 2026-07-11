from flask import Blueprint, jsonify, request

from service import learning_group_service

bp = Blueprint("learning_group_controller", __name__)


def _group_dto(group):
    if group is None:
        return None
    return {"groupId": group.group_id, "name": group.name}


@bp.route("", methods=["GET"])
def get_all_groups():
    groups = learning_group_service.get_all_groups()
    return jsonify({"groups": [_group_dto(g) for g in groups]})


@bp.route("", methods=["POST"])
def create_group():
    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name must not be empty"}), 400
    group = learning_group_service.create_group(name)
    return jsonify(_group_dto(group)), 201


@bp.route("/<string:group_id>", methods=["DELETE"])
def delete_group(group_id: str):
    learning_group_service.delete_group(group_id)
    return "", 204


@bp.route("/active", methods=["GET"])
def get_active_group():
    group = learning_group_service.get_active_group()
    return jsonify({"activeGroup": _group_dto(group)})


@bp.route("/active", methods=["PUT"])
def set_active_group():
    group_id = (request.json or {}).get("groupId")  # None = keine Gruppe
    group = learning_group_service.set_active_group(group_id)
    return jsonify({"activeGroup": _group_dto(group)})
