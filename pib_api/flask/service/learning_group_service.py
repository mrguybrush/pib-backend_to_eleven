from typing import List, Optional

from app.app import db
from model.learning_group_model import AppSettings, LearningGroup
from model.pose_model import Pose
from model.program_model import Program

_SETTINGS_ID = 1


def get_all_groups() -> List[LearningGroup]:
    return LearningGroup.query.order_by(LearningGroup.name.asc()).all()


def create_group(name: str) -> LearningGroup:
    group = LearningGroup(name=name)
    db.session.add(group)
    db.session.flush()
    return group


def delete_group(group_id: str) -> None:
    group = LearningGroup.query.filter_by(group_id=group_id).one()
    # keep the group's programs/poses, just detach them (they become
    # "ungrouped" and show up when no group is active)
    Program.query.filter_by(learning_group_id=group.id).update(
        {"learning_group_id": None}
    )
    Pose.query.filter_by(learning_group_id=group.id).update(
        {"learning_group_id": None}
    )
    settings = _get_settings()
    if settings.active_learning_group_id == group.id:
        settings.active_learning_group_id = None
    db.session.delete(group)
    db.session.flush()


def get_active_group() -> Optional[LearningGroup]:
    settings = _get_settings()
    if settings.active_learning_group_id is None:
        return None
    return LearningGroup.query.filter_by(
        id=settings.active_learning_group_id
    ).first()


def set_active_group(group_id: Optional[str]) -> Optional[LearningGroup]:
    """group_id None/empty = no active group (show everything)."""
    settings = _get_settings()
    if not group_id:
        settings.active_learning_group_id = None
        db.session.flush()
        return None
    group = LearningGroup.query.filter_by(group_id=group_id).one()
    settings.active_learning_group_id = group.id
    db.session.flush()
    return group


def active_group_db_id() -> Optional[int]:
    """Internal (integer) id of the active group, for query filters and
    for assigning newly created programs/poses - None if no group active."""
    return _get_settings().active_learning_group_id


def resolve_group_db_id(group_id: Optional[str]) -> Optional[int]:
    """External group_id (UUID, as used by the frontend) -> internal
    integer id, or None if group_id is empty/None (= unassign)."""
    if not group_id:
        return None
    return LearningGroup.query.filter_by(group_id=group_id).one().id


def group_db_id_to_external(db_id: Optional[int]) -> Optional[str]:
    """Internal integer id -> external group_id (UUID), or None."""
    if db_id is None:
        return None
    group = LearningGroup.query.filter_by(id=db_id).first()
    return group.group_id if group else None


def _get_settings() -> AppSettings:
    settings = AppSettings.query.filter_by(id=_SETTINGS_ID).first()
    if settings is None:
        settings = AppSettings(id=_SETTINGS_ID, active_learning_group_id=None)
        db.session.add(settings)
        db.session.flush()
    return settings
