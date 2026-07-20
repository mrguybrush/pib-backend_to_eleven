"""
Layer 3 (live-mirroring driver) + Layer 4 (timed static/dynamic capture).

Body/arm landmarks are pushed in from outside via tick(landmarks) - the
caller (gesture_node.py) receives them from the browser's own MediaPipe
PoseLandmarker (@mediapipe/tasks-vision) over a ROS topic, published via
rosbridge. Two earlier approaches ran detection on pib itself: on-device
(OAK-D VPU) and host-CPU (Raspberry Pi) - both hit resource/reliability
limits on pib's hardware (see camera package git history). The browser has
far more headroom and needs nothing installed on the robot for detection.

Builds only on already-existing, already-safe motor infrastructure:
- pib_api_client.motor_client.get_motor_settings() to read each motor's
  configured rotation_range_min/max (the SAME limits the manual joint-control
  UI is bound by) - never invented here.
- The existing "apply_joint_trajectory" ROS service (motors/motor_control.py)
  to actually move a motor - no new/parallel motor-control path.

Safety notes (see plan, "Sicherheit - besonders kritisch"):
- Every retargeted target is clamped to the motor's live rotation_range_min/max
  before being applied - non-negotiable, not optional.
- A conservative per-tick step limit (MAX_STEP_PER_TICK) smooths out
  tracking jitter so the arm can't jump on a single noisy frame.
- If a motor has no known settings (lookup failed), it is silently skipped
  rather than moved with a guessed range.
- Not yet live-tested against a real browser-side tracker - treat as
  unverified until tested together, arm power supervised, per the plan.
"""
import time
from dataclasses import replace

from datatypes.srv import ApplyJointTrajectory
from pib_api_client import (
    motor_client,
    motion_capture_mapping_client,
    motion_capture_settings_client,
    pose_client,
)
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from . import retargeting

# Same pose motors/relay_control.py parks the robot in on power on/off (see
# pib_motors/resting_pose.py) - reused here so a retargeted arm's "0 candidate
# degrees" (arms hanging, palms in) always lines up with the CURRENT resting
# pose instead of a stale hardcoded snapshot. Read-only here: unlike
# apply_resting_pose(), this never commands a motor, only reads positions to
# use as JointAssignment.offset values.
RESTING_POSE_NAME = "Startup/Resting"

# candidate_keys whose JointAssignment.offset is a deliberate saturation
# constant (retargeting.py's _HAND_OFFSET), not a rest-pose calibration -
# excluded from the live resting-pose offset override, see
# _with_rest_pose_offsets.
_HAND_CANDIDATE_KEYS = {"hand_openness"}

SAMPLE_PERIOD_S = 0.1  # 10 Hz, per user-specified capture resolution
# Max position change per 10Hz tick, in CENTIDEGREES (motor positions and
# rotation ranges are centidegrees, -9000..9000 = -90..+90 deg). 450 per
# tick = 45 deg/s - user asked for faster/more fluid movement twice now
# (started at 25 deg/s, then 35); still safety-bounded. (The old value of
# 4.0 dated from when positions were assumed to be plain degrees; in
# centidegrees it meant 0.4 deg/s, i.e. visually nothing moved.)
MAX_STEP_PER_TICK = 450.0
# Default EMA factor if the motion_capture_settings singleton can't be read.
# The live value (self.smoothing_alpha) comes from that settings row via the
# "Glaettung"-Regler above the mapping table - lower = smoother but laggier,
# higher = snappier/more direct. Applied to raw retarget targets before
# clamping/rate-limiting (independent of MAX_STEP_PER_TICK, which only
# bounds speed, not noise).
DEFAULT_SMOOTHING_ALPHA = 0.4


class GestureCapture:
    """
    One instance lives for the lifetime of gesture_node. start()/tick()/
    is_active() are driven externally (from GestureControlNode's timer),
    so this class has no ROS spin/threading of its own.
    """

    def __init__(self, node):
        self.node = node

        self.apply_client = node.create_client(
            ApplyJointTrajectory, "apply_joint_trajectory"
        )

        self.active = False
        # Plain live-mirroring, independent of any capture: motors follow the
        # person as long as this is on. Turning it off simply stops sending
        # new position commands - the servos hold their last commanded
        # position, so the robot freezes exactly where it is.
        self.mirroring = False
        # Only joints in this set are ever driven - the UI lets the user
        # click joints individually to include them in the mirroring.
        # Default (until a set_joints command arrives): the four joints whose
        # angles are robustly recoverable from the camera image - matches the
        # motion-capture page's preselection and the pre-selection behavior
        # of gesture captures started from the poses page.
        self.enabled_joints = {
            "elbow_left",
            "elbow_right",
            "shoulder_vertical_left",
            "shoulder_vertical_right",
        }
        # Latest raw retarget result (all mapped joints, unclamped), computed
        # on every tick with fresh landmarks - even while mirroring is off -
        # so the UI can always display live values per robot joint.
        self.latest_raw_targets = {}
        # Latest per-side candidate angles (both left AND right, before any
        # motor assignment is applied) - what the calibration wizard shows
        # live while the user moves and picks which side is which.
        self.latest_candidates = {}
        # Motor assignment (which tracked side + invert drives each motor).
        # Reloaded from the DB whenever mirroring/capture (re-)starts, same
        # as clamp_ranges - a mapping saved in the wizard should apply on
        # the next activation without requiring a node restart.
        self.assignment = retargeting.DEFAULT_ASSIGNMENT
        # Cached by _load_assignment() - {motor_name: position_centideg}
        # from the live "Startup/Resting" pose, reused to seed
        # last_targets/smoothed_targets on (re)start so the very first
        # commanded target ramps from the resting pose instead of jumping
        # (see start()/start_mirroring()).
        self.rest_pose_offsets = {}
        # {motor_name: percent (0-100)} - populated alongside assignment,
        # used by _clamp_and_rate_limit to scale MAX_STEP_PER_TICK per motor.
        self.speed_percent = {}
        # EMA factor for _smooth(); refreshed from the motion_capture_settings
        # singleton on every start/reload (see _load_assignment).
        self.smoothing_alpha = DEFAULT_SMOOTHING_ALPHA
        self.mode = None
        self.start_time = None
        self.end_time = None
        self.last_sample_time = 0.0
        self.last_targets = {}
        # EMA-smoothed retarget targets (centidegrees), keyed by motor name -
        # separate from last_targets, which holds the post-clamp/rate-limit
        # value actually applied to the motor.
        self.smoothed_targets = {}
        self.clamp_ranges = {}
        self.frames = []
        self.result = None  # set once a capture finishes; consumed+cleared by GestureControlNode

    def is_active(self) -> bool:
        return self.active

    def start_mirroring(self):
        if self.mirroring:
            return
        # Reload clamp ranges + joint-assignment each time - motor limits or
        # the calibrated mapping may have changed since the last session.
        self.clamp_ranges = self._load_clamp_ranges()
        self.assignment = self._load_assignment()
        # Seed with the live resting pose (not {}) - if motor power was
        # just switched on, relay_control.py parks the robot there right
        # before powering the servos, so the first rate-limited/smoothed
        # target ramps up from rest instead of an unbounded jump (see
        # _clamp_and_rate_limit: no "previous" means no rate limit at all).
        self.last_targets = dict(self.rest_pose_offsets)
        self.smoothed_targets = dict(self.rest_pose_offsets)
        self.mirroring = True
        self.node.get_logger().info(
            "live mirroring ON - "
            f"motors_with_known_range={list(self.clamp_ranges.keys())}"
        )

    def stop_mirroring(self):
        if not self.mirroring:
            return
        self.mirroring = False
        self.node.get_logger().info("live mirroring OFF - holding last position")

    def reload_assignment(self):
        """Re-reads the joint mapping from the DB immediately, without
        requiring mirroring to be toggled off/on - lets the calibration
        wizard apply a just-saved mapping right away."""
        self.assignment = self._load_assignment()

    def set_enabled_joints(self, joint_names):
        """Restrict mirroring/capture to these motors (names as in pibdata.db).
        Unknown names are ignored with a warning."""
        known = set(retargeting.MAPPED_MOTOR_NAMES)
        requested = set(joint_names)
        for unknown in requested - known:
            self.node.get_logger().warn(f"ignoring unknown joint: {unknown}")
        self.enabled_joints = requested & known
        self.node.get_logger().info(
            f"enabled joints: {sorted(self.enabled_joints) or '(none)'}"
        )

    def start(self, mode: str, duration_s: float):
        if mode not in ("static", "dynamic"):
            self.node.get_logger().error(f"unknown capture mode: {mode}")
            return
        self.mode = mode
        self.active = True
        self.start_time = time.monotonic()
        self.end_time = self.start_time + duration_s
        self.last_sample_time = 0.0
        self.frames = []
        self.clamp_ranges = self._load_clamp_ranges()
        self.assignment = self._load_assignment()
        # seed from resting pose, same reasoning as start_mirroring()
        self.last_targets = dict(self.rest_pose_offsets)
        self.smoothed_targets = dict(self.rest_pose_offsets)
        self.node.get_logger().info(
            f"gesture capture started: mode={mode} duration={duration_s}s "
            f"motors_with_known_range={list(self.clamp_ranges.keys())}"
        )

    def stop(self):
        """Manual/early stop (e.g. hand tracking lost, user cancels)."""
        if self.active:
            self._finish()

    def tick(self, landmarks):
        """landmarks: {"pose": {name: [x,y,score(,z)]}, "hands": {"left"/
        "right": {name: [x,y,z]}}} dict from the browser (see
        retargeting.compute_candidates), or None if nothing has been
        received recently (see gesture_node.py's staleness check) - in that
        case this tick just holds position."""
        # Always retarget fresh landmarks, even when nothing is mirrored -
        # the UI displays these live values in its joint table, and the
        # calibration wizard displays the raw per-side candidates.
        if landmarks:
            self.latest_candidates = retargeting.compute_candidates(landmarks)
            self.latest_raw_targets = self._smooth(
                retargeting.retarget(landmarks, assignment=self.assignment)
            )
        else:
            self.latest_candidates = {}
            self.latest_raw_targets = {}

        if not (self.active or self.mirroring):
            return

        now = time.monotonic()
        if landmarks:
            raw_targets = {
                name: target
                for name, target in self.latest_raw_targets.items()
                if name in self.enabled_joints
            }
            clamped = self._clamp_and_rate_limit(raw_targets)
            if clamped:
                self._apply(clamped)
                self.last_targets.update(clamped)

        if not self.active:
            return  # mirroring only - no sampling, no timed finish

        if self.mode == "dynamic" and now - self.last_sample_time >= SAMPLE_PERIOD_S:
            self.last_sample_time = now
            self.frames.append(
                {
                    "t_ms": int((now - self.start_time) * 1000),
                    "positions": dict(self.last_targets),
                }
            )

        if now >= self.end_time:
            self._finish()

    def _smooth(self, raw_targets: dict) -> dict:
        """EMA-smooths raw (unclamped) retarget targets per motor, to reduce
        pose-estimation jitter before MAX_STEP_PER_TICK's rate limit runs on
        top. Motors missing this frame keep no stale smoothed state (dropped
        below), so they re-initialize cleanly once observed again instead of
        gliding in from an old value."""
        smoothed = {}
        for motor_name, target in raw_targets.items():
            previous = self.smoothed_targets.get(motor_name)
            value = (
                target
                if previous is None
                else previous + self.smoothing_alpha * (target - previous)
            )
            smoothed[motor_name] = value
        self.smoothed_targets = smoothed
        return smoothed

    def _load_assignment(self):
        successful, dtos = motion_capture_mapping_client.get_joint_mapping()
        if not successful:
            self.node.get_logger().warn(
                "could not load joint mapping from pib-api; using defaults"
            )
            assignment = retargeting.DEFAULT_ASSIGNMENT
        else:
            overrides = [
                {
                    "motor_name": dto["motorName"],
                    "source_side": dto["sourceSide"],
                    "invert": dto["invert"],
                    "candidate_low_deg": dto.get("candidateLowDeg"),
                    "candidate_high_deg": dto.get("candidateHighDeg"),
                    "min_deg": dto.get("minDeg"),
                    "max_deg": dto.get("maxDeg"),
                    "speed_percent": dto.get("speedPercent"),
                }
                for dto in dtos
            ]
            assignment = retargeting.apply_assignment_overrides(overrides)
        # cached on self so start()/start_mirroring() can reuse the same
        # fetch to seed last_targets/smoothed_targets - see _with_rest_pose_offsets.
        self.rest_pose_offsets = self._load_rest_pose_offsets()
        assignment = self._with_rest_pose_offsets(assignment, self.rest_pose_offsets)
        assignment = self._with_two_point_calibration(assignment)
        self.speed_percent = {
            jm.motor_name: jm.speed_percent for jm in assignment
        }
        self._load_smoothing_alpha()
        return assignment

    def _load_smoothing_alpha(self):
        """Refreshes self.smoothing_alpha from the motion_capture_settings
        singleton (the "Glaettung"-Regler above the mapping table). Keeps the
        previous/default value if the settings can't be read."""
        successful, settings = motion_capture_settings_client.get_settings()
        if successful and settings and settings.get("smoothingAlpha") is not None:
            try:
                self.smoothing_alpha = float(settings["smoothingAlpha"])
            except (TypeError, ValueError):
                pass

    def _with_two_point_calibration(self, assignment: list) -> list:
        """Recomputes scale/offset for any JointAssignment whose
        candidate_low_deg/candidate_high_deg are both set (via the "Ist-Wert"
        buttons in the mapping table for the joint's "low"/"high" physical
        extremes), so candidate_low_deg maps exactly onto this motor's own
        rotation_range_min and candidate_high_deg onto rotation_range_max -
        the full servo span, no manual scale tuning. Runs AFTER
        _with_rest_pose_offsets, so an explicit two-point calibration always
        takes priority over the generic resting-pose-based fallback offset."""
        patched = []
        for jm in assignment:
            if jm.candidate_low_deg is None or jm.candidate_high_deg is None:
                patched.append(jm)
                continue
            # retarget() negates the raw candidate first when invert=True -
            # apply the same transform to the calibration anchors here, so
            # a saved calibration stays correct if invert is toggled later.
            low = -jm.candidate_low_deg if jm.invert else jm.candidate_low_deg
            high = -jm.candidate_high_deg if jm.invert else jm.candidate_high_deg
            span = high - low
            lo_hi = self.clamp_ranges.get(jm.motor_name)
            if abs(span) < 1e-6 or lo_hi is None:
                patched.append(jm)
                continue
            lo, hi = lo_hi
            scale = (hi - lo) / span
            offset = lo - scale * low
            patched.append(replace(jm, scale=scale, offset=offset))
        return patched

    def _load_rest_pose_offsets(self) -> dict:
        """Reads the live RESTING_POSE_NAME pose's motor positions from the
        pib-api - the same pose relay_control.py parks the robot in on power
        on/off, editable by the user on the Poses page. Returns {} (i.e. the
        hardcoded fallback offsets baked into retargeting.py's
        DEFAULT_ASSIGNMENT apply) if the pose can't be loaded."""
        successful, pose = pose_client.get_pose_by_name(RESTING_POSE_NAME)
        if not successful or pose is None:
            self.node.get_logger().warn(
                f"could not find pose '{RESTING_POSE_NAME}'; "
                "falling back to retargeting.py's baked-in rest offsets"
            )
            return {}
        successful, motor_positions = pose_client.get_motor_positions_of_pose(
            pose["poseId"]
        )
        if not successful or motor_positions is None:
            self.node.get_logger().warn(
                f"could not load motor positions of pose '{RESTING_POSE_NAME}'; "
                "falling back to retargeting.py's baked-in rest offsets"
            )
            return {}
        return {
            mp["motorName"]: mp["position"]
            for mp in motor_positions["motorPositions"]
        }

    def _with_rest_pose_offsets(self, assignment: list, rest_offsets: dict) -> list:
        """Overrides each arm/shoulder JointAssignment's offset with its
        live resting-pose position, so a candidate angle of 0 (arms hanging,
        palms in) always retargets to the robot's CURRENT rest pose instead
        of the value it happened to have when this code was written. Hand
        motors are left untouched - their offset is a deliberate saturation
        constant (see retargeting.py's _HAND_OFFSET), not a rest-pose
        calibration, and re-purposing it here would blow past the finger
        motors' real range."""
        if not rest_offsets:
            return assignment
        patched = []
        for jm in assignment:
            if jm.candidate_key in _HAND_CANDIDATE_KEYS or jm.motor_name not in rest_offsets:
                patched.append(jm)
                continue
            patched.append(replace(jm, offset=float(rest_offsets[jm.motor_name])))
        return patched

    def _load_clamp_ranges(self):
        ranges = {}
        for jm in retargeting.DEFAULT_ASSIGNMENT:
            successful, settings = motor_client.get_motor_settings(jm.motor_name)
            if successful and settings:
                ranges[jm.motor_name] = (
                    settings["rotationRangeMin"],
                    settings["rotationRangeMax"],
                )
            else:
                self.node.get_logger().warn(
                    f"no motor settings for {jm.motor_name}; it will not be mirrored"
                )
        return ranges

    def _clamp_and_rate_limit(self, raw_targets: dict) -> dict:
        clamped = {}
        for motor_name, target in raw_targets.items():
            if motor_name not in self.clamp_ranges:
                continue  # unknown range -> never move this motor, no guessing
            lo, hi = self.clamp_ranges[motor_name]
            target = max(lo, min(hi, target))

            previous = self.last_targets.get(motor_name)
            if previous is not None:
                delta = target - previous
                max_step = MAX_STEP_PER_TICK * (
                    self.speed_percent.get(motor_name, 100.0) / 100.0
                )
                if abs(delta) > max_step:
                    target = previous + max_step * (1 if delta > 0 else -1)
            clamped[motor_name] = int(round(target))
        return clamped

    def _apply(self, targets: dict):
        if not self.apply_client.service_is_ready():
            return
        for motor_name, position in targets.items():
            jt = JointTrajectory()
            jt.joint_names = [motor_name]
            point = JointTrajectoryPoint()
            point.positions.append(position)
            jt.points = [point]
            request = ApplyJointTrajectory.Request()
            request.joint_trajectory = jt
            self.apply_client.call_async(request)  # fire-and-forget

    def _finish(self):
        self.active = False
        if self.mode == "static":
            self.result = {"mode": "static", "positions": dict(self.last_targets)}
        else:
            self.result = {"mode": "dynamic", "sample_rate_hz": 1.0 / SAMPLE_PERIOD_S, "frames": self.frames}
        self.node.get_logger().info(f"gesture capture finished: mode={self.mode}")
