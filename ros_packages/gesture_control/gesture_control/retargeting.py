"""
Layer 2 (Retargeting): pure geometry, no neural networks.

Two-stage design, so the user can fix mis-routed joints themselves without
touching code:

  1. compute_candidates(payload) - for every trackable joint ("elbow",
     "shoulder_vertical", ...) computes a raw angle in DEGREES for BOTH the
     tracked person's left and right side independently. This is the
     "what does the camera see" stage and never mentions motor names.

  2. retarget(payload, assignment) - applies a JointAssignment list that
     says, per ROBOT MOTOR, which candidate + which tracked side + whether
     to invert the sign feeds it. DEFAULT_ASSIGNMENT reproduces the
     historical same-side behaviour (motor "elbow_left" <- candidate
     "elbow", side "left"), but every entry can be overridden - see
     motion_capture_mapping_client.get_joint_mapping() / the calibration
     wizard in cerebra's Motion-Capture page (settings > "Zuordnung neu
     kalibrieren"). That wizard is the fix for "erkannte Bewegung landet
     manchmal auf dem falschen Arm": instead of guessing at the source of a
     left/right mix-up (mirrored webcam vs. robot camera, a MediaPipe
     handedness quirk, ...), the user watches the live left/right numbers
     while moving and picks whichever one is actually their arm.

Conventions:
- Landmark payload: {"pose": {name: [x, y, score] or [x, y, score, z]},
  "hands": {"left": {name: [x,y,z]}, "right": {...}}}, as published by
  browser-pose-tracker.service.ts. "hands" entries are only present for a
  side when a hand was actually detected there this frame.
- Motor names / target positions are centidegrees, matching each motor's
  configured rotation_range_min/max in pibdata.db (-9000..9000 = -90..+90
  deg) - the same convention apply_joint_trajectory already uses.
- pose coordinates: x/z pre-scaled by frame aspect, y downward, z negative
  towards the camera (MediaPipe convention) - see browser-pose-tracker.
"""
import math
from dataclasses import dataclass, replace
from typing import Callable, Optional

Vec3 = tuple  # (x, y, z)


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


# --- per-side candidate computations ---------------------------------------
# Each function returns a single side's angle in degrees, or None if the
# required points aren't present/visible this frame.


def _elbow(pose: dict, side: str) -> Optional[float]:
    """flexion: 0 = fully stretched arm, grows as the elbow bends"""
    try:
        s, e, w = pose[f"{side}_shoulder"], pose[f"{side}_elbow"], pose[f"{side}_wrist"]
    except KeyError:
        return None
    return 180.0 - _vertex_angle(s, e, w)


def _shoulder_vertical(pose: dict, side: str) -> Optional[float]:
    """arm raise: 0 = arm hanging along the torso, 90 = horizontal"""
    try:
        h, s, e = pose[f"{side}_hip"], pose[f"{side}_shoulder"], pose[f"{side}_elbow"]
    except KeyError:
        return None
    return _vertex_angle(h, s, e)


def _shoulder_horizontal(pose: dict, side: str) -> Optional[float]:
    """azimuth of the upper arm in the horizontal plane: 0 = arm pointing
    sideways, positive = towards the camera (forward). Only meaningful when
    the arm is raised enough to have a horizontal direction; requires z."""
    try:
        s, e = pose[f"{side}_shoulder"], pose[f"{side}_elbow"]
        other = pose["right_shoulder" if side == "left" else "left_shoulder"]
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


def _upper_arm_rotation(pose: dict, side: str) -> Optional[float]:
    """rotation of the forearm around the upper-arm axis. 0 = forearm
    hanging straight down from the elbow; requires z and a bent elbow."""
    try:
        s, e, w = pose[f"{side}_shoulder"], pose[f"{side}_elbow"], pose[f"{side}_wrist"]
    except KeyError:
        return None
    axis = _normalize(_sub(e, s))
    if axis is None:
        return None
    forearm = _sub(w, e)
    if _norm(_perp_component(forearm, axis)) < _MIN_DIRECTION_LENGTH:
        return None  # arm almost stretched - rotation is unobservable
    return _signed_angle_around_axis(_DOWN, forearm, axis)


def _lower_arm_rotation_from_hand(hand: dict, elbow: Vec3) -> Optional[float]:
    """Pronation/supination from real hand landmarks: palm normal (cross of
    the hand's "forward" and "across" directions) projected around the
    elbow->wrist axis. Far more precise than the pose-only fallback below,
    since it uses the actual palm plane instead of two low-confidence
    pose keypoints."""
    try:
        wrist, index_mcp, middle_mcp, pinky_mcp = (
            hand["wrist"],
            hand["index_mcp"],
            hand["middle_mcp"],
            hand["pinky_mcp"],
        )
    except KeyError:
        return None
    axis = _normalize(_sub(wrist, elbow))
    if axis is None:
        return None
    forward = _sub(middle_mcp, wrist)
    across = _sub(pinky_mcp, index_mcp)
    normal = _cross(forward, across)
    if _norm(_perp_component(normal, axis)) < _MIN_DIRECTION_LENGTH / 2:
        return None
    return _signed_angle_around_axis(_DOWN, normal, axis)


def _lower_arm_rotation_from_pose(pose: dict, side: str) -> Optional[float]:
    """Fallback pronation/supination estimate from the Pose model's coarse
    hand keypoints (pinky/index), used only when no real hand landmark data
    is available for this side this frame."""
    try:
        e, w = pose[f"{side}_elbow"], pose[f"{side}_wrist"]
        pinky, index = pose[f"{side}_pinky"], pose[f"{side}_index"]
    except KeyError:
        return None
    axis = _normalize(_sub(w, e))
    if axis is None:
        return None
    hand = _sub(index, pinky)
    if _norm(_perp_component(hand, axis)) < _MIN_DIRECTION_LENGTH / 2:
        return None
    return _signed_angle_around_axis(_DOWN, hand, axis)


def _lower_arm_rotation(pose: dict, hands: dict, side: str) -> Optional[float]:
    hand = hands.get(side)
    if hand:
        try:
            elbow = pose[f"{side}_elbow"]
        except KeyError:
            elbow = None
        if elbow is not None:
            from_hand = _lower_arm_rotation_from_hand(hand, elbow)
            if from_hand is not None:
                return from_hand
    return _lower_arm_rotation_from_pose(pose, side)


def _hand_openness(hand: dict) -> Optional[float]:
    """0 = closed fist, 100 = fully open/spread hand. Average distance from
    the 5 fingertips to the wrist, normalized by a hand-size reference
    (wrist -> middle-finger knuckle) so it stays roughly scale-invariant
    across hand size / distance to camera. Drives the whole hand (all finger
    motors of a side) as one open/close signal - individual per-finger
    control was tried but MediaPipe's per-finger landmarks proved too noisy
    to feel like real detection. The 0.9/2.3 reference ratios are a first
    estimate (no closed-fist hardware reference was available) - tune
    per-hand-row in the mapping table if open/close doesn't reach the ends."""
    try:
        wrist = hand["wrist"]
        middle_mcp = hand["middle_mcp"]
        tips = [
            hand[name]
            for name in ("thumb_tip", "index_tip", "middle_tip", "ring_tip", "pinky_tip")
        ]
    except KeyError:
        return None
    ref = _norm(_sub(middle_mcp, wrist))
    if ref < 1e-6:
        return None
    avg_tip_dist = sum(_norm(_sub(t, wrist)) for t in tips) / len(tips)
    ratio = avg_tip_dist / ref
    openness = (ratio - 0.9) / (2.3 - 0.9) * 100.0
    return max(0.0, min(100.0, openness))


# --- candidate registry -----------------------------------------------------

# candidate_key -> function(pose, hands, side) -> degrees|None
CANDIDATE_FUNCTIONS: dict = {
    "elbow": lambda pose, hands, side: _elbow(pose, side),
    "shoulder_vertical": lambda pose, hands, side: _shoulder_vertical(pose, side),
    "shoulder_horizontal": lambda pose, hands, side: _shoulder_horizontal(pose, side),
    "upper_arm_rotation": lambda pose, hands, side: _upper_arm_rotation(pose, side),
    "lower_arm_rotation": lambda pose, hands, side: _lower_arm_rotation(pose, hands, side),
    "hand_openness": lambda pose, hands, side: _hand_openness(hands.get(side, {})),
}


def _as_xyz(points: dict) -> dict:
    """{name: [x,y,score] or [x,y,score,z]} -> {name: (x,y,z)}"""
    return {name: (v[0], v[1], v[3] if len(v) > 3 else 0.0) for name, v in points.items()}


def compute_candidates(payload: dict) -> dict:
    """
    payload: {"pose": {name: [x,y,score(,z)]}, "hands": {"left"/"right":
              {name: [x,y,z]}}}, as received from the browser.

    Returns {candidate_key: {"left": degrees|None, "right": degrees|None}}
    for every entry in CANDIDATE_FUNCTIONS - the raw "what does the camera
    see" values, independent of any robot motor.
    """
    pose = _as_xyz(payload.get("pose", {}))
    hands = {side: _as_xyz(pts) for side, pts in payload.get("hands", {}).items()}

    candidates = {}
    for key, fn in CANDIDATE_FUNCTIONS.items():
        candidates[key] = {
            "left": fn(pose, hands, "left"),
            "right": fn(pose, hands, "right"),
        }
    return candidates


# --- motor assignment --------------------------------------------------------


@dataclass
class JointAssignment:
    motor_name: str  # motor name exactly as in pibdata.db
    candidate_key: str  # key into CANDIDATE_FUNCTIONS / compute_candidates()
    source_side: str = "left"  # "left" or "right" - which tracked side drives this motor
    invert: bool = False
    # Fallback degrees -> centidegrees mapping, used only until the joint
    # is two-point calibrated (see candidate_low_deg/candidate_high_deg
    # below) - at that point gesture_capture.py's
    # _with_two_point_calibration() recomputes both from the calibration,
    # overriding whatever is set here.
    scale: float = 100.0
    offset: float = 0.0  # centidegrees, added after scaling
    # Per-installation two-point calibration, set via the "Ist-Wert"
    # buttons in the mapping table: the RAW candidate reading (same units
    # shown live in the left/right columns) at the joint's "low" and
    # "high" physical extremes (e.g. arm hanging vs. arm fully raised).
    # When both are set, scale/offset are recomputed at runtime so
    # candidate_low_deg maps exactly onto this motor's own
    # rotation_range_min and candidate_high_deg onto rotation_range_max -
    # no manual scale tuning, and no assumption that "neutral" reads
    # exactly 0 (real camera/body geometry rarely does).
    candidate_low_deg: Optional[float] = None
    candidate_high_deg: Optional[float] = None
    # Absolute target limits in MOTOR DEGREES (applied after scale/offset/
    # calibration, converted to centidegrees internally) - lets the user
    # rein in the full servo range if desired, e.g. "never rotate this
    # joint backward past its resting position". None = no extra limit,
    # the motor's own rotation_range_min/max is the only bound.
    min_deg: Optional[float] = None
    max_deg: Optional[float] = None
    # Per-motor speed cap: percent (0-100) of gesture_capture's
    # MAX_STEP_PER_TICK. 100 = full global speed.
    speed_percent: float = 100.0


def _default_side_for_motor(motor_name: str) -> str:
    return "left" if motor_name.endswith("_left") or "_left_" in motor_name else "right"


# Per user requirement: shoulder, upper arm and lower arm including
# rotations, plus hand open/close, both sides. Hip/torso are deliberately
# not mapped, legs don't exist as motors at all.
# source_side defaults to the motor's own side (i.e. reproduces the
# historical same-side behaviour) - override via the mapping table in
# cerebra's Motion-Capture page if that turns out to be mirrored for a given
# camera setup.
#
# offset: centidegrees added after scaling, so that a candidate angle of 0
# (person standing with arms hanging, palms facing inward) maps to the
# robot's own matching rest pose instead of the arbitrary position "0"
# happens to be. FALLBACK ONLY: gesture_capture.py's _load_assignment()
# overrides these at runtime with the live "Startup/Resting" pose's actual
# motor positions (same pose relay_control.py parks the robot in on power
# on/off, editable on the Poses page) - these constants only apply if that
# lookup fails. The values below are a one-time snapshot (2026-07-15) of
# that pose, not a substitute for it. shoulder_horizontal's candidate is
# unobservable (None) with arms hanging, but the offset is set for
# consistency anyway and takes effect once the arm is raised.
_ELBOW_OFFSET = -5500.0  # rest pose: elbow -55 deg
_SHOULDER_VERTICAL_OFFSET = -6600.0  # rest pose: shoulder_vertical -66 deg
_SHOULDER_HORIZONTAL_OFFSET = 8600.0  # rest pose: shoulder_horizontal 86 deg
_UPPER_ARM_ROTATION_OFFSET = -2000.0  # rest pose: upper_arm_rotation -20 deg
_LOWER_ARM_ROTATION_OFFSET = 3600.0  # rest pose: lower_arm_rotation 36 deg

# Each finger's stretch/opposition candidate is 0 .. 100; no closed-fist
# hardware reference was available, so this deliberately saturates at each
# finger motor's own DB-configured rotation range (see _clamp_and_rate_limit
# in gesture_capture.py) rather than at a calibrated "true" open/closed
# angle. If a finger moves too far, the wrong way, or not at all, tune it
# per-row in the mapping table (scale/min_deg/max_deg/invert) - no code
# change needed.
_HAND_SCALE = 200.0
_HAND_OFFSET = -10000.0

DEFAULT_ASSIGNMENT = [
    JointAssignment("elbow_left", "elbow", "left", offset=_ELBOW_OFFSET),
    JointAssignment("elbow_right", "elbow", "right", offset=_ELBOW_OFFSET),
    JointAssignment(
        "shoulder_vertical_left",
        "shoulder_vertical",
        "left",
        offset=_SHOULDER_VERTICAL_OFFSET,
    ),
    JointAssignment(
        "shoulder_vertical_right",
        "shoulder_vertical",
        "right",
        offset=_SHOULDER_VERTICAL_OFFSET,
    ),
    JointAssignment(
        "shoulder_horizontal_left",
        "shoulder_horizontal",
        "left",
        offset=_SHOULDER_HORIZONTAL_OFFSET,
    ),
    JointAssignment(
        "shoulder_horizontal_right",
        "shoulder_horizontal",
        "right",
        offset=_SHOULDER_HORIZONTAL_OFFSET,
    ),
    JointAssignment(
        "upper_arm_left_rotation",
        "upper_arm_rotation",
        "left",
        offset=_UPPER_ARM_ROTATION_OFFSET,
        # Deliberately no forward-only min_deg default anymore - min_deg/
        # max_deg are now user-set absolute target limits (see mapping
        # table), which the user can set empirically for their own camera
        # setup instead of a code guess baked in ahead of time.
    ),
    JointAssignment(
        "upper_arm_right_rotation",
        "upper_arm_rotation",
        "right",
        offset=_UPPER_ARM_ROTATION_OFFSET,
    ),
    JointAssignment(
        "lower_arm_left_rotation",
        "lower_arm_rotation",
        "left",
        offset=_LOWER_ARM_ROTATION_OFFSET,
    ),
    JointAssignment(
        "lower_arm_right_rotation",
        "lower_arm_rotation",
        "right",
        offset=_LOWER_ARM_ROTATION_OFFSET,
    ),
    # All finger motors of a side share the one hand_openness candidate -
    # the "Hand links/rechts" table row drives them together (open/close).
    JointAssignment(
        "index_left_stretch", "hand_openness", "left", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "index_right_stretch", "hand_openness", "right", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "middle_left_stretch", "hand_openness", "left", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "middle_right_stretch", "hand_openness", "right", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "ring_left_stretch", "hand_openness", "left", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "ring_right_stretch", "hand_openness", "right", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "pinky_left_stretch", "hand_openness", "left", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "pinky_right_stretch", "hand_openness", "right", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "thumb_left_stretch", "hand_openness", "left", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "thumb_right_stretch", "hand_openness", "right", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "thumb_left_opposition", "hand_openness", "left", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
    JointAssignment(
        "thumb_right_opposition", "hand_openness", "right", scale=_HAND_SCALE, offset=_HAND_OFFSET
    ),
]

# all motor names this module can produce targets for (for UIs and clients)
MAPPED_MOTOR_NAMES = [jm.motor_name for jm in DEFAULT_ASSIGNMENT]

# candidate_key per motor, for building calibration-wizard UIs
MOTOR_TO_CANDIDATE = {jm.motor_name: jm.candidate_key for jm in DEFAULT_ASSIGNMENT}


def apply_assignment_overrides(overrides: list) -> list:
    """
    overrides: list of dicts with motor_name/source_side/invert/
    candidate_low_deg/candidate_high_deg/min_deg/max_deg/speed_percent (as
    returned by motion_capture_mapping_client.get_joint_mapping()). Returns
    a full JointAssignment list: DEFAULT_ASSIGNMENT with any matching
    entries' fields replaced. Unknown motor names in `overrides` are
    ignored (e.g. a stale row from a previous mapping version). scale/
    offset are NOT overridable directly here - they're recomputed from
    candidate_low_deg/candidate_high_deg once both are set (see
    gesture_capture.py's _with_two_point_calibration), or for arm/shoulder
    motors kept in sync with the live resting pose as a pre-calibration
    fallback (_with_rest_pose_offsets); for hand motors pre-calibration
    it's a deliberate saturation constant (see _HAND_OFFSET above).
    """
    by_motor = {o["motor_name"]: o for o in overrides or []}
    result = []
    for default in DEFAULT_ASSIGNMENT:
        override = by_motor.get(default.motor_name)
        if override is None:
            result.append(default)
            continue
        # dataclasses.replace() rather than reconstructing by hand, so
        # fields the mapping table doesn't cover (offset, ...) always carry
        # over from the default instead of silently resetting whenever a
        # new field is added here. dict.get() only falls back to the
        # default when the KEY is missing entirely - a stored None (e.g.
        # "not yet calibrated", or an intentional "no limit") is returned
        # as-is.
        result.append(
            replace(
                default,
                source_side=override.get("source_side", default.source_side),
                invert=bool(override.get("invert", default.invert)),
                candidate_low_deg=override.get(
                    "candidate_low_deg", default.candidate_low_deg
                ),
                candidate_high_deg=override.get(
                    "candidate_high_deg", default.candidate_high_deg
                ),
                min_deg=override.get("min_deg", default.min_deg),
                max_deg=override.get("max_deg", default.max_deg),
                speed_percent=override.get("speed_percent", default.speed_percent),
            )
        )
    return result


def retarget(payload: dict, assignment: list = None) -> dict:
    """
    payload: see compute_candidates().
    assignment: JointAssignment list (default: DEFAULT_ASSIGNMENT, i.e. no
    per-installation calibration applied).

    Returns {motor_name: target_position_centidegrees (int)} for every
    assignment entry whose source candidate/side is currently observable.
    Missing/unobservable joints are skipped for this frame rather than
    guessed - the mirroring driver holds the last known-good position in
    that case.
    """
    candidates = compute_candidates(payload)
    targets = {}
    for jm in assignment or DEFAULT_ASSIGNMENT:
        side_values = candidates.get(jm.candidate_key)
        if not side_values:
            continue
        deg = side_values.get(jm.source_side)
        if deg is None:
            continue
        if jm.invert:
            deg = -deg
        target = jm.offset + jm.scale * deg
        # min_deg/max_deg are absolute target limits in MOTOR DEGREES,
        # applied after calibration - convert to centidegrees to compare.
        if jm.min_deg is not None:
            target = max(jm.min_deg * 100.0, target)
        if jm.max_deg is not None:
            target = min(jm.max_deg * 100.0, target)
        targets[jm.motor_name] = int(round(target))
    return targets
