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

from datatypes.srv import ApplyJointTrajectory
from pib_api_client import motor_client
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from . import retargeting

SAMPLE_PERIOD_S = 0.1  # 10 Hz, per user-specified capture resolution
# Max position change per 10Hz tick, in CENTIDEGREES (motor positions and
# rotation ranges are centidegrees, -9000..9000 = -90..+90 deg). 250 per
# tick = 25 deg/s - fast enough to visibly follow, slow enough to be safe.
# (The old value of 4.0 dated from when positions were assumed to be plain
# degrees; in centidegrees it meant 0.4 deg/s, i.e. visually nothing moved.)
MAX_STEP_PER_TICK = 250.0


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
        self.mode = None
        self.start_time = None
        self.end_time = None
        self.last_sample_time = 0.0
        self.last_targets = {}
        self.clamp_ranges = {}
        self.frames = []
        self.result = None  # set once a capture finishes; consumed+cleared by GestureControlNode

    def is_active(self) -> bool:
        return self.active

    def start_mirroring(self):
        if self.mirroring:
            return
        # Reload clamp ranges each time - motor limits may have been changed
        # in the joint-control UI since the last session.
        self.clamp_ranges = self._load_clamp_ranges()
        self.last_targets = {}
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
        self.last_targets = {}
        self.frames = []
        self.clamp_ranges = self._load_clamp_ranges()
        self.node.get_logger().info(
            f"gesture capture started: mode={mode} duration={duration_s}s "
            f"motors_with_known_range={list(self.clamp_ranges.keys())}"
        )

    def stop(self):
        """Manual/early stop (e.g. hand tracking lost, user cancels)."""
        if self.active:
            self._finish()

    def tick(self, landmarks):
        """landmarks: {name: [x, y, score]} dict from the browser, or None
        if nothing has been received recently (see gesture_node.py's
        staleness check) - in that case this tick just holds position."""
        # Always retarget fresh landmarks, even when nothing is mirrored -
        # the UI displays these live values in its joint table.
        if landmarks:
            self.latest_raw_targets = retargeting.retarget(landmarks)
        else:
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

    def _load_clamp_ranges(self):
        ranges = {}
        for jm in retargeting.DEFAULT_MAPPING:
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
                if abs(delta) > MAX_STEP_PER_TICK:
                    target = previous + MAX_STEP_PER_TICK * (1 if delta > 0 else -1)
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
