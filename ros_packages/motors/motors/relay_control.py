import time

import rclpy
from rclpy.node import Node
from rclpy.publisher import Publisher
from rclpy.service import Service
from rclpy.executors import SingleThreadedExecutor
from pib_api_client import system_settings_client
from pib_motors.bricklet import set_ssr_state, solid_state_relay_bricklet
from pib_motors.motor import motors
from pib_motors.resting_pose import apply_resting_pose
from datatypes.msg import SolidStateRelayState
from datatypes.srv import SetSolidStateRelay
from std_msgs.msg import Int32
from trajectory_msgs.msg import JointTrajectory

# how long the servos get to physically reach the resting pose before the
# relay cuts their power on shutdown
POWER_OFF_DELAY_SECONDS = 5.0

# How often to check whether the auto-off timeout has been reached. Short
# enough that the shutoff happens reasonably promptly after the configured
# minutes elapse, long enough not to spam the settings API.
AUTO_OFF_CHECK_INTERVAL_SECONDS = 30.0

# How often to publish the remaining-seconds countdown shown in cerebra's
# settings page. Computed from the cached setting (refreshed only every
# AUTO_OFF_CHECK_INTERVAL_SECONDS above, not on every tick) plus
# last_activity_time, so this does NOT add extra load on the settings API -
# it's cheap enough to run at 1Hz for a smooth-looking countdown.
COUNTDOWN_PUBLISH_INTERVAL_SECONDS = 1.0


class RelayControl(Node):

    def __init__(self):
        super().__init__("relay_control")
        self.state: SolidStateRelayState = SolidStateRelayState()
        self.state.turned_on: bool = False
        self.relay: BrickletSolidStateRelayV2 | None = solid_state_relay_bricklet
        self.relay_available: bool = self.relay is not None

        # Publisher for solid state relay status
        self.relay_state_publisher: Publisher = self.create_publisher(
            SolidStateRelayState, "solid_state_relay_state", 10
        )

        # Service for setting the solid state relay state
        self.set_solid_state_relay_state_service: Service = self.create_service(
            SetSolidStateRelay,
            "set_solid_state_relay_state",
            self.set_solid_state_relay_state,
        )

        # Publish relay status every second to catch external changes (e.g. brickv)
        self.polling_timer = self.create_timer(1.0, self.poll_relay_state)

        # Auto-off: any published joint_trajectory means the robot is being
        # actively driven, regardless of source (manual sliders, Blockly
        # programs, gestures, pose application - they all end up here via
        # apply_joint_trajectory in motor_control.py). Used to detect
        # inactivity for the auto-off timer below.
        self.last_activity_time = time.monotonic()
        self.joint_trajectory_subscription = self.create_subscription(
            JointTrajectory, "joint_trajectory", self._on_joint_trajectory, 10
        )

        # Cached by _check_auto_off (every AUTO_OFF_CHECK_INTERVAL_SECONDS)
        # and read by _publish_countdown (every second) - the countdown must
        # not hit the settings API itself, see comment on the constant above.
        self._cached_auto_off_minutes: int | None = None

        self.auto_off_countdown_publisher: Publisher = self.create_publisher(
            Int32, "auto_off_seconds_remaining", 10
        )
        self.auto_off_timer = self.create_timer(
            AUTO_OFF_CHECK_INTERVAL_SECONDS, self._check_auto_off
        )
        self.countdown_timer = self.create_timer(
            COUNTDOWN_PUBLISH_INTERVAL_SECONDS, self._publish_countdown
        )
        # Populate the cache immediately instead of waiting for the first
        # AUTO_OFF_CHECK_INTERVAL_SECONDS tick, so the countdown is correct
        # right after this node starts.
        self._check_auto_off()

        self.get_logger().info("Now Running RELAY_CONTROL")

    def _on_joint_trajectory(self, _msg: JointTrajectory) -> None:
        self.last_activity_time = time.monotonic()

    def _check_auto_off(self) -> None:
        """Moves to resting pose and cuts power once the configured
        inactivity timeout is reached - prevents the servos from
        overheating if the robot is left powered on and idle."""
        successful, auto_off_minutes = system_settings_client.get_auto_off_minutes()
        self._cached_auto_off_minutes = auto_off_minutes if successful else None
        if not self.state.turned_on:
            return
        if not self._cached_auto_off_minutes or self._cached_auto_off_minutes <= 0:
            return
        idle_seconds = time.monotonic() - self.last_activity_time
        if idle_seconds < self._cached_auto_off_minutes * 60:
            return
        self.get_logger().info(
            f"auto-off: no activity for {self._cached_auto_off_minutes} min, powering down"
        )
        self.update_relay_state(False)

    def _publish_countdown(self) -> None:
        """Publishes seconds remaining until auto-off, consumed by cerebra's
        settings page. -1 means "not applicable" (disabled, or robot
        already off) - the frontend hides the countdown in that case."""
        minutes = self._cached_auto_off_minutes
        if not self.state.turned_on or not minutes or minutes <= 0:
            remaining_seconds = -1
        else:
            idle_seconds = time.monotonic() - self.last_activity_time
            remaining_seconds = max(0, round(minutes * 60 - idle_seconds))
        msg = Int32()
        msg.data = remaining_seconds
        self.auto_off_countdown_publisher.publish(msg)

    def set_solid_state_relay_state(
        self, request: SetSolidStateRelay.Request, response: SetSolidStateRelay.Response
    ):
        """callback function for 'set_solid_state_relay_state' service"""
        request_state: SolidStateRelayState = request.solid_state_relay_state
        successful = self.update_relay_state(request_state.turned_on)
        response.successful = successful
        return response

    def update_relay_state(self, turned_on: bool) -> bool:
        """attempts to update the solid state relay, and returns whether this was successful"""
        if self.state.turned_on == turned_on:
            return self.relay_available
        try:
            if turned_on:
                # Pre-position all servos at the resting pose while they are
                # still unpowered: the moment power comes on, everything
                # moves gently into the resting pose at once - replaces the
                # old one-motor-at-a-time startup choreography.
                self.get_logger().info(
                    "pre-positioning resting pose, then powering servos on"
                )
                apply_resting_pose(motors, self.get_logger().warn)
                set_ssr_state(True)
            else:
                # Park the robot before cutting power: command the resting
                # pose while still powered, give the servos time to actually
                # get there, then switch off.
                self.get_logger().info(
                    f"moving to resting pose, powering off in {POWER_OFF_DELAY_SECONDS}s"
                )
                apply_resting_pose(motors, self.get_logger().warn)
                time.sleep(POWER_OFF_DELAY_SECONDS)
                set_ssr_state(False)
            self.state.turned_on = turned_on
        except Exception as e:
            self.get_logger().error(
                f"following error occurred while trying to update solid state relay state: {str(e)}."
            )
            return False

        relay_state = SolidStateRelayState()
        relay_state.turned_on = self.state.turned_on

        self.relay_state_publisher.publish(relay_state)
        return True

    def poll_relay_state(self):
        if self.relay is None:
            return
        try:
            current_relay_state = self.relay.get_state()
            self.relay_available = True
        except Exception as e:
            if self.relay_available:
                self.get_logger().error(f"Error getting relay state: {str(e)}")
            self.relay_available = False
            return

        self.state.turned_on = current_relay_state

        msg = SolidStateRelayState()
        msg.turned_on = self.state.turned_on
        self.relay_state_publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = RelayControl()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    executor.spin()
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
