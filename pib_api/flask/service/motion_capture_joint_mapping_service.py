from typing import Any, List
from model.motion_capture_joint_mapping_model import MotionCaptureJointMapping
from app.app import db


def get_all_mappings() -> List[MotionCaptureJointMapping]:
    return MotionCaptureJointMapping.query.order_by(
        MotionCaptureJointMapping.motor_name.asc()
    ).all()


def replace_all_mappings(
    mapping_dtos: List[dict[str, Any]],
) -> List[MotionCaptureJointMapping]:
    """
    Ersetzt die komplette Zuordnung durch die uebergebene Liste (vom
    Kalibrierungs-Assistenten als Ganzes gesendet, ein Eintrag pro Motor).
    """
    MotionCaptureJointMapping.query.delete()
    mappings = [
        MotionCaptureJointMapping(
            motor_name=dto["motor_name"],
            source_side=dto["source_side"],
            invert=dto["invert"],
            candidate_low_deg=dto.get("candidate_low_deg"),
            candidate_high_deg=dto.get("candidate_high_deg"),
            min_deg=dto.get("min_deg"),
            max_deg=dto.get("max_deg"),
            speed_percent=dto.get("speed_percent", 100.0),
        )
        for dto in mapping_dtos
    ]
    db.session.add_all(mappings)
    db.session.flush()
    return get_all_mappings()
