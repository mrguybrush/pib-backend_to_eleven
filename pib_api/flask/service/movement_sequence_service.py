from typing import Any, List

from app.app import db
from model.movement_sequence_model import MovementSequence
from model.movement_sequence_frame_model import MovementSequenceFrame


def get_all_movement_sequences() -> List[MovementSequence]:
    return MovementSequence.query.filter().order_by(MovementSequence.deletable.asc()).all()


def get_movement_sequence(sequence_id: str) -> MovementSequence:
    return MovementSequence.query.filter(MovementSequence.sequence_id == sequence_id).one()


def create_movement_sequence(sequence_dto: dict[str, Any]) -> MovementSequence:
    frame_dtos = sequence_dto["frames"]
    frames = [_create_frame(index, dto) for index, dto in enumerate(frame_dtos)]
    sequence = MovementSequence(
        name=sequence_dto["name"],
        sample_rate_hz=sequence_dto.get("sample_rate_hz", 10.0),
        frames=frames,
    )
    db.session.add(sequence)
    db.session.flush()
    return sequence


def delete_movement_sequence(sequence_id: str) -> None:
    sequence = get_movement_sequence(sequence_id)
    if not sequence.deletable:
        raise ValueError(f"Movement sequence '{sequence.name}' is not deletable")
    db.session.delete(sequence)
    db.session.flush()


def rename_movement_sequence(sequence_id: str, sequence_dto: dict[str, Any]) -> MovementSequence:
    sequence = get_movement_sequence(sequence_id)
    if not sequence.deletable:
        raise ValueError(f"Movement sequence '{sequence.name}' cannot be renamed.")
    sequence.name = sequence_dto["name"]
    db.session.flush()
    return sequence


def _create_frame(index: int, frame_dto: dict[str, Any]) -> MovementSequenceFrame:
    frame = MovementSequenceFrame(
        frame_index=index,
        timestamp_ms=frame_dto["timestamp_ms"],
        positions=frame_dto["positions"],
    )
    db.session.add(frame)
    return frame
