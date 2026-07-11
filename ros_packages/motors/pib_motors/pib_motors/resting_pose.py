"""
Shared helper for pre-positioning all motors at the "Startup/Resting" pose.

Servo bricklets accept and store position commands even while the solid
state relay has the servos unpowered (the bricklets themselves are powered
via the stack) - so "moving to resting pose" splits into two very different
uses:

- BEFORE powering on: write the resting positions while everything is
  still unpowered. The instant the relay closes, every servo moves to the
  resting pose simultaneously and gently (soft acceleration settings) -
  no staggered one-motor-at-a-time startup choreography needed anymore.
- BEFORE powering off: command the resting pose while still powered, give
  the servos a moment to physically get there, then cut power - so the
  robot is parked in a defined position instead of collapsing wherever it
  happened to be.

Used by relay_control.py (both relay edges) and motor_control.py (initial
pre-positioning at node start).
"""
from typing import Callable

from pib_api_client import pose_client
from pib_motors.motor import Motor

RESTING_POSE_NAME = "Startup/Resting"


def apply_resting_pose(motors: list[Motor], log: Callable[[str], None]) -> bool:
    """Writes the resting-pose position to every motor that appears in the
    pose (positions are clamped per-motor by Motor.set_position). Returns
    False if the pose could not be loaded from the pib-api."""
    successful, pose = pose_client.get_pose_by_name(RESTING_POSE_NAME)
    if not successful or pose is None:
        log(f"could not find pose '{RESTING_POSE_NAME}' in pib-api")
        return False

    successful, motor_positions = pose_client.get_motor_positions_of_pose(
        pose["poseId"]
    )
    if not successful:
        log(f"could not load motor positions of pose '{RESTING_POSE_NAME}'")
        return False

    name_to_position = {
        mp["motorName"]: mp["position"]
        for mp in motor_positions["motorPositions"]
    }
    for motor in motors:
        if motor.name not in name_to_position:
            continue
        if not motor.check_if_motor_is_connected():
            continue
        motor.set_position(name_to_position[motor.name])
    return True
