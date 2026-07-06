from service import movement_sequence_service
from schema.movement_sequence_schema import (
    movement_sequences_schema,
    movement_sequence_schema,
    create_movement_sequence_schema,
    movement_sequence_schema_name_only,
)
from flask import jsonify, request, Blueprint

bp = Blueprint("movement_sequence_controller", __name__)


@bp.route("", methods=["POST"])
def create_movement_sequence():
    sequence_dto = create_movement_sequence_schema.load(request.json)
    sequence = movement_sequence_service.create_movement_sequence(sequence_dto)
    return movement_sequence_schema.dump(sequence), 201


@bp.route("", methods=["GET"])
def get_all_movement_sequences():
    sequences = movement_sequence_service.get_all_movement_sequences()
    return jsonify({"movementSequences": movement_sequences_schema.dump(sequences)})


@bp.route("/<string:sequence_id>", methods=["GET"])
def get_movement_sequence(sequence_id: str):
    sequence = movement_sequence_service.get_movement_sequence(sequence_id)
    return movement_sequence_schema.dump(sequence)


@bp.route("/<string:sequence_id>", methods=["DELETE"])
def delete_movement_sequence(sequence_id: str):
    movement_sequence_service.delete_movement_sequence(sequence_id)
    return "", 204


@bp.route("/<string:sequence_id>", methods=["PATCH"])
def rename_movement_sequence(sequence_id: str):
    sequence_dto = movement_sequence_schema_name_only.load(request.json)
    sequence = movement_sequence_service.rename_movement_sequence(sequence_id, sequence_dto)
    return movement_sequence_schema.dump(sequence)
