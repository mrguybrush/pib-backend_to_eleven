#!/usr/bin/python3
"""
ROS node for gesture/movement-sequence capture. Detection happens entirely
in the browser (@mediapipe/tasks-vision on the user's own webcam); this node
only receives already-computed landmarks over rosbridge, retargets them to
motor angles, and drives the capture state machine (gesture_capture.py).

Runs independently of the camera package on purpose - a landmark stream has
nothing to do with pib's own camera hardware, and keeping this decoupled
means a future camera-side issue can never again take the gesture feature
down with it (see git history: two earlier on-robot detection approaches
both destabilized the OAK-D Lite).
"""
import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .depth_fusion import DepthFusion
from .gesture_capture import GestureCapture

TICK_PERIOD_S = 0.1  # 10 Hz, matches gesture_capture.SAMPLE_PERIOD_S
LANDMARKS_STALE_AFTER_S = 0.5  # ignore landmarks older than this (dropped connection etc.)


class GestureControlNode(Node):
    def __init__(self):
        super().__init__("gesture_control_node")

        self.latest_landmarks = None
        self.latest_landmarks_time = 0.0

        self.landmarks_subscription = self.create_subscription(
            String, "browser_pose_landmarks", self.on_landmarks, 10
        )
        # Echtes Stereo-Tiefenbild der OAK-D (nur waehrend Motion Capture
        # aktiv, siehe depth_fusion.py) - ersetzt die vom Browser-Modell nur
        # geschaetzte z-Koordinate durch Messwerte.
        self.depth_fusion = DepthFusion()
        self.depth_map_subscription = self.create_subscription(
            String, "depth_map", self.on_depth_map, 10
        )
        self.gesture_capture_control_subscription = self.create_subscription(
            String, "gesture_capture_control", self.on_capture_control, 10
        )
        self.gesture_capture_result_publisher = self.create_publisher(
            String, "gesture_capture_result", 10
        )
        # Live retarget values for the UI's joint table: on every tick with
        # fresh landmarks, the raw (unclamped) target per mapped robot joint
        # is published - independent of whether mirroring is on.
        self.retarget_targets_publisher = self.create_publisher(
            String, "gesture_retarget_targets", 10
        )
        # Raw per-side candidates (left AND right, before any motor
        # assignment) for the calibration wizard's live left/right display.
        self.retarget_candidates_publisher = self.create_publisher(
            String, "gesture_retarget_candidates", 10
        )

        self.gesture_capture = GestureCapture(self)
        self.timer = self.create_timer(TICK_PERIOD_S, self.on_timer)
        self.get_logger().info("gesture_control_node ready")

    def on_landmarks(self, msg: String):
        try:
            self.latest_landmarks = json.loads(msg.data)
            self.latest_landmarks_time = time.monotonic()
        except json.JSONDecodeError:
            self.get_logger().error(f"invalid browser_pose_landmarks payload: {msg.data}")

    def on_depth_map(self, msg: String):
        self.depth_fusion.update(msg.data)

    def on_capture_control(self, msg: String):
        try:
            command = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().error(f"invalid gesture_capture_control payload: {msg.data}")
            return

        action = command.get("action")
        if action == "start":
            self.gesture_capture.start(
                mode=command.get("mode", "static"),
                duration_s=float(command.get("duration_s", 5.0)),
            )
        elif action == "stop":
            self.gesture_capture.stop()
        elif action == "mirror_start":
            self.gesture_capture.start_mirroring()
        elif action == "mirror_stop":
            self.gesture_capture.stop_mirroring()
        elif action == "set_joints":
            self.gesture_capture.set_enabled_joints(command.get("joints", []))
        elif action == "reload_mapping":
            self.gesture_capture.reload_assignment()
        else:
            self.get_logger().error(f"unknown gesture_capture_control action: {action}")

    def on_timer(self):
        fresh = (time.monotonic() - self.latest_landmarks_time) < LANDMARKS_STALE_AFTER_S
        payload = self.latest_landmarks if fresh else None
        if payload is not None:
            # Mit frischem Tiefenbild werden die 2D-Landmarks in echte
            # metrische 3D-Punkte umgerechnet; ohne geht die Payload
            # unveraendert durch (siehe depth_fusion.py).
            payload = self.depth_fusion.fuse(payload)
        self.gesture_capture.tick(payload)

        targets_msg = String()
        targets_msg.data = json.dumps(
            {
                "targets": self.gesture_capture.latest_raw_targets,
                "mirroring": self.gesture_capture.mirroring,
                "enabled": sorted(self.gesture_capture.enabled_joints),
            }
        )
        self.retarget_targets_publisher.publish(targets_msg)

        candidates_msg = String()
        candidates_msg.data = json.dumps(self.gesture_capture.latest_candidates)
        self.retarget_candidates_publisher.publish(candidates_msg)

        if self.gesture_capture.result is not None:
            result_msg = String()
            result_msg.data = json.dumps(self.gesture_capture.result)
            self.gesture_capture_result_publisher.publish(result_msg)
            self.gesture_capture.result = None


def main(args=None):
    rclpy.init(args=args)
    node = GestureControlNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
