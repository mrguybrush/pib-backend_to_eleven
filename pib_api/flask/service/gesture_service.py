from typing import Any, List

from app.app import db
from model.gesture_model import Gesture
from model.gesture_motor_position_model import GestureMotorPosition


def get_all_gestures() -> List[Gesture]:
    return Gesture.query.filter().order_by(Gesture.deletable.asc()).all()


def get_gesture(gesture_id: str) -> Gesture:
    return Gesture.query.filter(Gesture.gesture_id == gesture_id).one()


def create_gesture(gesture_dto: dict[str, Any]) -> Gesture:
    motor_position_dtos = gesture_dto["motor_positions"]
    motor_positions = [_create_motor_position(dto) for dto in motor_position_dtos]
    gesture = Gesture(name=gesture_dto["name"], motor_positions=motor_positions)
    db.session.add(gesture)
    db.session.flush()
    return gesture


def delete_gesture(gesture_id: str) -> None:
    gesture = get_gesture(gesture_id)
    if not gesture.deletable:
        raise ValueError(f"Gesture '{gesture.name}' is not deletable")
    db.session.delete(gesture)
    db.session.flush()


def rename_gesture(gesture_id: str, gesture_dto: dict[str, Any]) -> Gesture:
    gesture = get_gesture(gesture_id)
    if not gesture.deletable:
        raise ValueError(f"Gesture '{gesture.name}' cannot be renamed.")
    gesture.name = gesture_dto["name"]
    db.session.flush()
    return gesture


def _create_motor_position(motor_position_dto: dict[str, Any]) -> GestureMotorPosition:
    motor_position = GestureMotorPosition(
        position=motor_position_dto["position"],
        motor_name=motor_position_dto["motor_name"],
    )
    db.session.add(motor_position)
    return motor_position
