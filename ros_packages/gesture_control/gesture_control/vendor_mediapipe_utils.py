"""
Geometry helpers + gesture-name classification. angle()/distance()/
recognize_gesture() are a minimal, trimmed port from:
https://github.com/geaxgx/depthai_hand_tracker (mediapipe_utils.py), MIT License.

Detection itself (hand + body landmarks) runs in the browser via
@mediapipe/tasks-vision, on the user's own PC/iPad/webcam - not on pib's
OAK-D or Raspberry Pi. Two earlier approaches (on-device VPU NN, then
host-CPU MediaPipe) both ran into resource limits or reliability issues on
pib's hardware; the browser has far more headroom and needs no code running
on the robot at all for detection. Landmarks arrive here already as plain
{name: [x, y, score]} dicts over a ROS topic (see gesture_node.py) - this
module only does the geometry math on them.
"""
import numpy as np

np.seterr(over="ignore")


# --- Body keypoint name -> index -------------------------------------------
# MediaPipe Pose (33-point) landmark indices, as sent by the browser's
# PoseLandmarker.
BODY_KP = {
    "nose": 0,
    "left_eye": 2,
    "right_eye": 5,
    "left_ear": 7,
    "right_ear": 8,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}

# --- Hand (MediaPipe, 21 pts) keypoint name -> index -----------------------
HAND_KP = {
    "wrist": 0,
    "thumb_cmc": 1, "thumb_mcp": 2, "thumb_ip": 3, "thumb_tip": 4,
    "index_mcp": 5, "index_pip": 6, "index_dip": 7, "index_tip": 8,
    "middle_mcp": 9, "middle_pip": 10, "middle_dip": 11, "middle_tip": 12,
    "ring_mcp": 13, "ring_pip": 14, "ring_dip": 15, "ring_tip": 16,
    "little_mcp": 17, "little_pip": 18, "little_dip": 19, "little_tip": 20,
}


class HandRegion:
    """Result of one hand detection + landmark inference (trimmed)."""

    def __init__(self):
        self.rect_x_center_a = None
        self.rect_y_center_a = None
        self.rect_w_a = None
        self.rect_h_a = None
        self.rotation = None
        self.lm_score = None
        self.handedness = None
        self.label = None
        self.norm_landmarks = None  # (21,3) normalized, rotated-rect-relative -> used for gesture geometry
        self.landmarks = None  # (21,2) pixel coords in source image
        self.gesture = None


def distance(a, b):
    """a, b: 2 points (2D or 3D np.array)"""
    return np.linalg.norm(a - b)


def angle(a, b, c):
    """Interior angle (degrees) at vertex b, formed by points a-b-c."""
    ba = a - b
    bc = c - b
    cosine_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc))
    cosine_angle = np.clip(cosine_angle, -1.0, 1.0)
    return np.degrees(np.arccos(cosine_angle))


def recognize_gesture(hand: HandRegion):
    """
    Classifies a HandRegion's norm_landmarks into one of 8 static poses:
    FIVE, FIST, OK, PEACE, ONE, TWO, THREE, FOUR - or None.
    Sets hand.gesture. Ported unmodified (logic-wise) from mediapipe_utils.py.
    """
    d_3_5 = distance(hand.norm_landmarks[3], hand.norm_landmarks[5])
    d_2_3 = distance(hand.norm_landmarks[2], hand.norm_landmarks[3])
    a0 = angle(hand.norm_landmarks[0], hand.norm_landmarks[1], hand.norm_landmarks[2])
    a1 = angle(hand.norm_landmarks[1], hand.norm_landmarks[2], hand.norm_landmarks[3])
    a2 = angle(hand.norm_landmarks[2], hand.norm_landmarks[3], hand.norm_landmarks[4])
    thumb_state = 1 if (a0 + a1 + a2 > 460 and d_3_5 / d_2_3 > 1.2) else 0

    def finger_state(tip, dip, pip):
        if hand.norm_landmarks[tip][1] < hand.norm_landmarks[dip][1] < hand.norm_landmarks[pip][1]:
            return 1
        elif hand.norm_landmarks[pip][1] < hand.norm_landmarks[tip][1]:
            return 0
        return -1

    index_state = finger_state(8, 7, 6)
    middle_state = finger_state(12, 11, 10)
    ring_state = finger_state(16, 15, 14)
    little_state = finger_state(20, 19, 18)

    states = (thumb_state, index_state, middle_state, ring_state, little_state)
    gestures = {
        (1, 1, 1, 1, 1): "FIVE",
        (0, 0, 0, 0, 0): "FIST",
        (1, 0, 0, 0, 0): "OK",
        (0, 1, 1, 0, 0): "PEACE",
        (0, 1, 0, 0, 0): "ONE",
        (1, 1, 0, 0, 0): "TWO",
        (1, 1, 1, 0, 0): "THREE",
        (0, 1, 1, 1, 1): "FOUR",
    }
    hand.gesture = gestures.get(states)
