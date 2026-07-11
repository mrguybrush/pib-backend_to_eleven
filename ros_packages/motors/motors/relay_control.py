import time

import rclpy
from rclpy.node import Node
from rclpy.publisher import Publisher
from rclpy.service import Service
from rclpy.executors import SingleThreadedExecutor
from pib_motors.bricklet import set_ssr_state, solid_state_relay_bricklet
from pib_motors.motor import motors
from pib_motors.resting_pose import apply_resting_pose
from datatypes.msg import SolidStateRelayState
from datatypes.srv import SetSolidStateRelay

# how long the servos get to physically reach the resting pose before the
# relay cuts their power on shutdown
POWER_OFF_DELAY_SECONDS = 5.0


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

        self.get_logger().info("Now Running RELAY_CONTROL")

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
