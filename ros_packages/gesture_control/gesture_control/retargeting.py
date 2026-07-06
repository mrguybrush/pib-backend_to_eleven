"""
Layer 2 (Retargeting): pure geometry, no neural networks.

Maps named landmark points (received from the browser's MediaPipe
PoseLandmarker via gesture_node.py) to pib joint-angle targets.

Conventions:
- Motor names are EXACTLY the names stored in pibdata.db (table `motor`,
  e.g. "elbow_left", "shoulder_vertical_left") - the same names that
  pib_api_client.motor_client and the apply_joint_trajectory service use.
  (An earlier version used made-up uppercase names like "ELBOW_LEFT";
  those never matched anything, so no joint ever moved.)
- Target positions are CENTIDEGREES, matching the motors' configured
  rotation_range_min/max in the database (-9000..9000 = -90..+90 deg).
- Landmark payload per point: [x, y, score] or [x, y, score, z]. The
  browser sends aspect-corrected coordinates with y pointing DOWN and
  z negative towards the camera (MediaPipe convention). Without z, the
  rotation joints cannot be computed and are simply skipped.
- Mapping is same-side: the tracked person's right arm drives pib's
  right arm.

The angle->position conversions below (scale/offset/sign) are geometric
best guesses; per-joint fine-tuning happens by adjusting scale/offset here
or the motor's invert-flag / rotation range in the database. Every target
is additionally clamped to the motor's live rotation range by the caller
(gesture_capture.py) before anything moves.
"""
import math
from dataclasses import dataclass
from typing import Callable, Optional

Vec3 = tuple  # (x, y, z)


@dataclass
class JointMapping:
    motor_name: str  # motor name exactly as in pibdata.db
    compute: Callable  # (points: {name: Vec3}) -> Optional[float], angle in degrees
    scale: float = 100.0  # degrees -> centidegrees
    offset: float = 0.0  # centidegrees, added after scaling


# --- vector helpers -------------------------------------------------------


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec3) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vec3) -> Optional[Vec3]:
    n = _norm(a)
    if n < 1e-9:
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


def _vertex_angle(a: Vec3, b: Vec3, c: Vec3) -> float:
    """interior angle at vertex b, in degrees"""
    ba = _sub(a, b)
    bc = _sub(c, b)
    m = _norm(ba) * _norm(bc)
    if m < 1e-12:
        return 0.0
    cos = max(-1.0, min(1.0, _dot(ba, bc) / m))
    return math.degrees(math.acos(cos))


def _perp_component(v: Vec3, axis_unit: Vec3) -> Vec3:
    """component of v perpendicular to the (unit-length) axis"""
    d = _dot(v, axis_unit)
    return (v[0] - d * axis_unit[0], v[1] - d * axis_unit[1], v[2] - d * axis_unit[2])


def _signed_angle_around_axis(ref: Vec3, v: Vec3, axis_unit: Vec3) -> Optional[float]:
    """signed angle (degrees) from ref to v, both projected onto the plane
    perpendicular to axis_unit; positive per right-hand rule around the axis"""
    ref_p = _perp_component(ref, axis_unit)
    v_p = _perp_component(v, axis_unit)
    if _norm(ref_p) < 1e-6 or _norm(v_p) < 1e-6:
        return None
    sin = _dot(axis_unit, _cross(ref_p, v_p))
    cos = _dot(ref_p, v_p)
    return math.degrees(math.atan2(sin, cos))


# gravity/"down" in image coordinates (y grows downwards, person upright)
_DOWN: Vec3 = (0.0, 1.0, 0.0)

# minimum length of a projected direction vector before we trust an angle
# derived from it (landmark coordinates are roughly body-sized, ~0..1.8)
_MIN_DIRECTION_LENGTH = 0.05


# --- per-joint angle computations -----------------------------------------


def _elbow(points: dict, side: str) -> Optional[float]:
    """flexion: 0 = fully stretched arm, grows as the elbow bends"""
    try:
        s, e, w = points[f"{side}_shoulder"], points[f"{side}_elbow"], points[f"{side}_wrist"]
    except KeyError:
        return None
    return 180.0 - _vertex_angle(s, e, w)


def _shoulder_vertical(points: dict, side: str) -> Optional[float]:
    """arm raise: 0 = arm hanging along the torso, 90 = horizontal"""
    try:
        h, s, e = points[f"{side}_hip"], points[f"{side}_shoulder"], points[f"{side}_elbow"]
    except KeyError:
        return None
    return _vertex_angle(h, s, e)


def _shoulder_horizontal(points: dict, side: str) -> Optional[float]:
    """azimuth of the upper arm in the horizontal plane: 0 = arm pointing
    sideways, positive = towards the camera (forward). Only meaningful when
    the arm is raised enough to have a horizontal direction; requires z."""
    try:
        s, e = points[f"{side}_shoulder"], points[f"{side}_elbow"]
        other = points["right_shoulder" if side == "left" else "left_shoulder"]
    except KeyError:
        return None
    v = _sub(e, s)
    horiz = (v[0], 0.0, v[2])
    if _norm(horiz) < _MIN_DIRECTION_LENGTH:
        return None  # arm hangs (nearly vertical) - azimuth undefined/noisy
    out = _normalize((s[0] - other[0], 0.0, s[2] - other[2]))
    if out is None:
        return None
    outward = _dot(horiz, out)
    forward = -v[2]  # MediaPipe: closer to camera = more negative z
    return math.degrees(math.atan2(forward, outward))


def _upper_arm_rotation(points: dict, side: str) -> Optional[float]:
    """rotation of the forearm around the upper-arm axis. 0 = forearm
    hanging straight down from the elbow; requires z and a bent elbow."""
    try:
        s, e, w = points[f"{side}_shoulder"], points[f"{side}_elbow"], points[f"{side}_wrist"]
    except KeyError:
        return None
    axis = _normalize(_sub(e, s))
    if axis is None:
        return None
    forearm = _sub(w, e)
    if _norm(_perp_component(forearm, axis)) < _MIN_DIRECTION_LENGTH:
        return None  # arm almost stretched - rotation is unobservable
    return _signed_angle_around_axis(_DOWN, forearm, axis)


def _lower_arm_rotation(points: dict, side: str) -> Optional[float]:
    """pronation/supination of the forearm, estimated from the hand's
    pinky->index direction around the elbow->wrist axis; requires the
    hand keypoints (index/pinky) and z."""
    try:
        e, w = points[f"{side}_elbow"], points[f"{side}_wrist"]
        pinky, index = points[f"{side}_pinky"], points[f"{side}_index"]
    except KeyError:
        return None
    axis = _normalize(_sub(w, e))
    if axis is None:
        return None
    hand = _sub(index, pinky)
    if _norm(_perp_component(hand, axis)) < _MIN_DIRECTION_LENGTH / 2:
        return None
    # reference: hand-crease direction when the palm faces the body,
    # approximated by "down" projected perpendicular to the forearm
    return _signed_angle_around_axis(_DOWN, hand, axis)


# --- the mapping ------------------------------------------------------------

# Per user requirement: shoulder, upper arm and lower arm including
# rotations, both sides. Hip/torso and fingers are intentionally not mapped.
# offset examples: elbow 0 deg (stretched) -> centered on 0; the shoulder
# raise re-centers 0..180 deg onto the -9000..9000 motor range as needed.
DEFAULT_MAPPING = [
    JointMapping("elbow_left", lambda p: _elbow(p, "left")),
    JointMapping("elbow_right", lambda p: _elbow(p, "right")),
    JointMapping("shoulder_vertical_left", lambda p: _shoulder_vertical(p, "left")),
    JointMapping("shoulder_vertical_right", lambda p: _shoulder_vertical(p, "right")),
    JointMapping("shoulder_horizontal_left", lambda p: _shoulder_horizontal(p, "left")),
    JointMapping("shoulder_horizontal_right", lambda p: _shoulder_horizontal(p, "right")),
    JointMapping("upper_arm_left_rotation", lambda p: _upper_arm_rotation(p, "left")),
    JointMapping("upper_arm_right_rotation", lambda p: _upper_arm_rotation(p, "right")),
    JointMapping("lower_arm_left_rotation", lambda p: _lower_arm_rotation(p, "left")),
    JointMapping("lower_arm_right_rotation", lambda p: _lower_arm_rotation(p, "right")),
]

# all motor names this module can produce targets for (for UIs and clients)
MAPPED_MOTOR_NAMES = [jm.motor_name for jm in DEFAULT_MAPPING]


def retarget(points: dict, mapping: list = DEFAULT_MAPPING) -> dict:
    """
    points: {name: [x, y, score] or [x, y, score, z]} as received from the
            browser over the browser_pose_landmarks ROS topic
    Returns {motor_name: target_position_centidegrees (int)} for every
    mapping entry whose required points are present and whose angle is
    currently observable. Missing/unobservable joints are skipped for this
    frame rather than guessed - the mirroring driver holds the last
    known-good position in that case.
    """
    pts3 = {
        name: (v[0], v[1], v[3] if len(v) > 3 else 0.0) for name, v in points.items()
    }
    targets = {}
    for jm in mapping:
        deg = jm.compute(pts3)
        if deg is None:
            continue
        targets[jm.motor_name] = int(round(jm.offset + jm.scale * deg))
    return targets
