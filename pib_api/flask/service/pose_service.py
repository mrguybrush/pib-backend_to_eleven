from typing import Any, List

from sqlalchemy import or_

from app.app import db
from default_pose_constants import STARTUP_POSE_NAME
from model.pose_model import Pose
from model.motor_position_model import MotorPosition
from service import learning_group_service


def get_all_poses() -> List[Pose]:
    """With an active learning group: only that group's poses plus the
    non-deletable default poses (Startup/Resting stays always available).
    Without one: everything. Ordered by the user's drag&drop sort_index
    (NULL = never sorted, falls to the end, then by name)."""
    active_group_id = learning_group_service.active_group_db_id()
    query = Pose.query
    if active_group_id is not None:
        query = query.filter(
            or_(
                Pose.learning_group_id == active_group_id,
                Pose.deletable == False,  # noqa: E712 (SQLAlchemy expression)
            )
        )
    return query.order_by(
        Pose.deletable.asc(),
        db.func.coalesce(Pose.sort_index, 1_000_000).asc(),
        Pose.name.asc(),
    ).all()


def reorder_poses(pose_ids: List[str]) -> None:
    """Persists the drag&drop order of the pose list: sort_index = position
    in the given list. Poses not in the list keep their old index (they were
    filtered out client-side, e.g. by the active learning group)."""
    index_by_id = {pose_id: index for index, pose_id in enumerate(pose_ids)}
    poses = Pose.query.filter(Pose.pose_id.in_(pose_ids)).all()
    for pose in poses:
        pose.sort_index = index_by_id[pose.pose_id]
    db.session.flush()


def get_all_poses_admin() -> List[dict]:
    """Every pose regardless of the active group, with its group's external
    (UUID) id - for the "Programme zuordnen" assignment table, which needs
    to show and (re)assign everything, not just what's currently filtered
    into view."""
    poses = Pose.query.order_by(Pose.deletable.asc(), Pose.name.asc()).all()
    return [_pose_admin_dto(pose) for pose in poses]


def _pose_admin_dto(pose: Pose) -> dict:
    return {
        "poseId": pose.pose_id,
        "name": pose.name,
        "deletable": pose.deletable,
        "learningGroupId": learning_group_service.group_db_id_to_external(
            pose.learning_group_id
        ),
    }


def set_pose_group(pose_id: str, group_id: str) -> dict:
    pose = get_pose(pose_id)
    if not pose.deletable:
        raise ValueError(f"Pose '{pose.name}' cannot be reassigned.")
    pose.learning_group_id = learning_group_service.resolve_group_db_id(group_id)
    db.session.flush()
    return _pose_admin_dto(pose)


def copy_pose_to_group(pose_id: str, group_id: str) -> dict:
    # Resolve BEFORE creating any MotorPosition below - see the comment in
    # create_pose() about autoflush flushing not-yet-linked child rows.
    target_group_db_id = learning_group_service.resolve_group_db_id(group_id)
    source = get_pose(pose_id)
    name = _unique_pose_name(f"{source.name} (Kopie)")
    motor_positions = [
        _create_motor_position(
            {"position": mp.position, "motor_name": mp.motor_name}
        )
        for mp in source.motor_positions
    ]
    pose = Pose(
        name=name, motor_positions=motor_positions, learning_group_id=target_group_db_id
    )
    db.session.add(pose)
    db.session.flush()
    return _pose_admin_dto(pose)


def _unique_pose_name(base: str) -> str:
    if not Pose.query.filter_by(name=base).first():
        return base
    i = 2
    while True:
        candidate = f"{base} ({i})"
        if not Pose.query.filter_by(name=candidate).first():
            return candidate
        i += 1


def get_pose(pose_id: str) -> Pose:
    return Pose.query.filter(Pose.pose_id == pose_id).one()


def get_pose_by_name(pose_name: str) -> Pose:
    return Pose.query.filter(Pose.name == pose_name).one()


def create_pose(pose_dto: dict[str, Any]) -> Pose:
    # Must be read BEFORE any MotorPosition is added to the session below:
    # it runs a query, and SQLAlchemy's autoflush would otherwise flush
    # those already-added-but-not-yet-linked-to-a-pose MotorPosition rows
    # first, violating their NOT NULL pose_id column.
    active_learning_group_id = learning_group_service.active_group_db_id()
    motor_position_dtos = pose_dto["motor_positions"]
    motor_positions = [_create_motor_position(dto) for dto in motor_position_dtos]
    pose = Pose(
        name=pose_dto["name"],
        motor_positions=motor_positions,
        # new poses belong to the currently active learning group (None if
        # no group is active - then they're globally visible)
        learning_group_id=active_learning_group_id,
    )
    db.session.add(pose)
    db.session.flush()
    return pose


def delete_pose(pose_id: str) -> None:
    pose = get_pose(pose_id)
    if not pose.deletable:
        raise ValueError(f"Pose '{pose.name}' is not deletable")
    db.session.delete(pose)
    db.session.flush()


def _create_motor_position(motor_position_dto: dict[str, Any]) -> MotorPosition:
    motor_position = MotorPosition(
        position=motor_position_dto["position"],
        motor_name=motor_position_dto["motor_name"],
    )
    db.session.add(motor_position)
    return motor_position


def rename_pose(pose_id: str, pose_dto: dict[str, Any]) -> Pose:
    pose = get_pose(pose_id)
    if not pose.deletable:
        raise ValueError(f"Pose '{pose.name}' cannot be renamed.")
    pose.name = pose_dto["name"]
    db.session.flush()
    return pose


def update_motor_positions_of_pose(pose_id: str, pose_dto: dict[str, Any]) -> Pose:
    pose = get_pose(pose_id)
    if not pose.deletable and pose.name != STARTUP_POSE_NAME:
        raise ValueError(f"Pose '{pose.name}' cannot be updated.")
    motor_position_dtos = pose_dto["motor_positions"]
    if len(motor_position_dtos) != len(pose.motor_positions):
        raise ValueError("Number of motor positions does not match existing pose.")
    motor_name_to_position = {
        mp["motor_name"]: mp["position"] for mp in motor_position_dtos
    }
    for existing_mp in pose.motor_positions:
        if existing_mp.motor_name not in motor_name_to_position:
            raise ValueError(
                f"Motor '{existing_mp.motor_name}' not found in update request."
            )
        existing_mp.position = motor_name_to_position[existing_mp.motor_name]
    db.session.flush()
    return pose
