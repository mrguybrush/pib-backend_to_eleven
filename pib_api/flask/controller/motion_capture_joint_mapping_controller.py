from flask import Blueprint, jsonify, request

from schema.motion_capture_joint_mapping_schema import (
    motion_capture_joint_mappings_schema,
)
from service import motion_capture_joint_mapping_service

bp = Blueprint("motion_capture_joint_mapping_controller", __name__)


@bp.route("", methods=["GET"])
def get_joint_mapping():
    mappings = motion_capture_joint_mapping_service.get_all_mappings()
    return jsonify({"mappings": motion_capture_joint_mappings_schema.dump(mappings)})


@bp.route("", methods=["PUT"])
def replace_joint_mapping():
    mapping_dtos = motion_capture_joint_mappings_schema.load(
        request.json.get("mappings", [])
    )
    mappings = motion_capture_joint_mapping_service.replace_all_mappings(mapping_dtos)
    return jsonify({"mappings": motion_capture_joint_mappings_schema.dump(mappings)})
