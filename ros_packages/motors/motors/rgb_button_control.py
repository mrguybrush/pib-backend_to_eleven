import rclpy

from rclpy.node import Node
from rclpy.client import Client
from rclpy.task import Future
from tinkerforge.bricklet_rgb_led_button import BrickletRGBLEDButton
from pib_motors.bricklet import uid_to_rgb_led_bricklet
from datatypes.srv import (
    ProxyRunProgramStart,
    ProxyRunProgramStop,
    SetRgbButtonColor,
    GetRgbButtonState,
)
from datatypes.msg import ProxyRunProgramResult
from pib_api_client import button_programs_client, bricklet_client

ERROR_COLOR_DURATION_SECONDS = 2.0  # how long red stays before reverting to blue
BLUE_COLOR = (0, 0, 255)  # blue color for idle state
GREEN_COLOR = (0, 255, 0)  # green color for program running state
RED_COLOR = (255, 0, 0)  # red color for error state
POLL_INTERVAL_SECONDS = 5.0


class RGBButtonControl(Node):
    def __init__(self):
        super().__init__("rgb_button_control")
        self.rgb_led_bricklets: dict[str, BrickletRGBLEDButton] = (
            uid_to_rgb_led_bricklet
        )
        if not self.rgb_led_bricklets:
            self.get_logger().info("No RGB Led Button Bricklet found")

        for uid, bricklet in self.rgb_led_bricklets.items():
            try:
                bricklet.register_callback(
                    BrickletRGBLEDButton.CALLBACK_BUTTON_STATE_CHANGED,
                    lambda state, uid=uid: self.on_button_state_changed(uid, state),
                )
                self.get_logger().info(
                    f"Registered callback for RGB Button Bricklet with UID {uid}"
                )
            except Exception as e:
                self.get_logger().error(
                    f"Error registering callback for RGB Button Bricklet with UID {uid}: {str(e)}"
                )

        self.start_program_client: Client = self.create_client(
            ProxyRunProgramStart, "proxy_run_program_start"
        )
        self.start_program_client.wait_for_service()

        self.stop_program_client: Client = self.create_client(
            ProxyRunProgramStop, "proxy_run_program_stop"
        )
        self.stop_program_client.wait_for_service()

        self.program_result_subscriber = self.create_subscription(
            ProxyRunProgramResult,
            "proxy_run_program_result",
            self.program_result_callback,
            10,
        )

        # maps proxy_goal_id -> uid
        self.goal_to_uid: dict[str, str] = {}

        # bricklet_number (1,2,3 as used in the UI/Blockly) -> hardware uid,
        # so blocks can address a button by its number.
        self.number_to_uid: dict[int, str] = self._build_number_to_uid()

        # Buttons whose colour was explicitly set by a program via
        # set_rgb_button_color. Those are left alone by the periodic idle/
        # running colour management until the node restarts, so a
        # program-chosen colour actually sticks.
        self.manual_color_override: set[str] = set()

        # Services callable from Blockly-generated programs.
        self.set_color_service = self.create_service(
            SetRgbButtonColor, "set_rgb_button_color", self.set_rgb_button_color
        )
        self.get_state_service = self.create_service(
            GetRgbButtonState, "get_rgb_button_state", self.get_rgb_button_state
        )

        self.update_button_colors()

        self.create_timer(POLL_INTERVAL_SECONDS, self.update_button_colors)

        self.get_logger().info("Now Running RGB_BUTTON_CONTROL")

    def program_result_callback(self, msg: ProxyRunProgramResult) -> None:
        """Set button color to red on error (temporary), blue on success."""
        uid = self.goal_to_uid.pop(msg.proxy_goal_id, None)
        if not uid:
            return

        if msg.exit_code != 0:
            self.set_button_color(uid, *RED_COLOR)
            self.get_logger().warning(
                f"Program failed for UID {uid}, exit_code={msg.exit_code}"
            )
        else:
            self.set_button_color(uid, *BLUE_COLOR)
            self.get_logger().info(f"Program finished successfully for UID {uid}")

    def on_button_state_changed(self, uid: str, state) -> None:
        """Callback function for button press events."""
        if state == BrickletRGBLEDButton.BUTTON_STATE_PRESSED:
            # If program is running for this button, stop it
            running_goal_id = self.get_running_goal_id(uid)
            if running_goal_id:
                self.stop_program(running_goal_id, uid)
                return

            self.load_button_programs()
            program_number = self.uid_to_program.get(uid)
            if program_number:
                self.get_logger().info(
                    f"Starting program {program_number} for button with UID {uid}."
                )
                self.start_program(program_number, uid)
            else:
                self.get_logger().warning(
                    f"No program assigned to button with UID {uid}."
                )

    def get_running_goal_id(self, uid: str) -> str | None:
        """Returns the proxy_goal_id if a program is currently running for this button."""
        for goal_id, goal_uid in self.goal_to_uid.items():
            if goal_uid == uid:
                return goal_id
        return None

    def stop_program(self, proxy_goal_id: str, uid: str) -> None:
        """Stops a running program by proxy_goal_id."""
        request = ProxyRunProgramStop.Request()
        request.proxy_goal_id = proxy_goal_id
        future: Future = self.stop_program_client.call_async(request)

        def on_response(fut: Future):
            response = fut.result()
            if response:
                self.goal_to_uid.pop(proxy_goal_id, None)
                self.set_button_color(uid, *BLUE_COLOR)
                self.get_logger().info(
                    f"Stopped program for UID {uid}, proxy_goal_id={proxy_goal_id}"
                )

        future.add_done_callback(on_response)

    def load_button_programs(self) -> None:
        """Loads the button programs from the pib-api"""
        successful, button_programs_dto = button_programs_client.get_button_programs()
        if not successful:
            self.get_logger().error("Failed to load button programs from backend.")
            return

        self.uid_to_program = {}
        for button_program in button_programs_dto["buttonPrograms"]:
            uid = button_program.get("brickletUid")
            if uid:
                self.uid_to_program[uid] = button_program.get("programNumber")

    def start_program(self, program_number: str, uid: str) -> None:
        request = ProxyRunProgramStart.Request()
        request.program_number = program_number
        self.set_button_color(uid, *GREEN_COLOR)
        future: Future = self.start_program_client.call_async(request)

        def on_response(fut: Future):
            response = fut.result()
            if response:
                self.goal_to_uid[response.proxy_goal_id] = uid
                self.get_logger().info(
                    f"Started program {program_number} for UID {uid}, proxy_goal_id={response.proxy_goal_id}"
                )

        future.add_done_callback(on_response)

    def set_button_color(self, uid: str, r: int, g: int, b: int) -> None:
        bricklet = self.rgb_led_bricklets.get(uid)
        if not bricklet:
            return
        try:
            bricklet.set_color(r, g, b)
        except Exception as e:
            self.get_logger().error(f"Error setting color for UID {uid}: {str(e)}")

    def _build_number_to_uid(self) -> dict[int, str]:
        """Maps bricklet_number -> uid for RGB LED button bricklets, read
        from the pib-api bricklet table (same identity the UI uses)."""
        mapping: dict[int, str] = {}
        successful, dto = bricklet_client.get_all_bricklets()
        if not successful or not dto:
            self.get_logger().warning(
                "Could not load bricklets for number->uid mapping."
            )
            return mapping
        for bricklet in dto.get("bricklets", []):
            if (
                bricklet.get("type") == "RGB LED Button Bricklet"
                and bricklet.get("uid")
                and bricklet.get("brickletNumber") is not None
            ):
                mapping[int(bricklet["brickletNumber"])] = bricklet["uid"]
        return mapping

    # ----- Services for Blockly programs -----
    def set_rgb_button_color(
        self, request: SetRgbButtonColor.Request, response: SetRgbButtonColor.Response
    ) -> SetRgbButtonColor.Response:
        uid = self.number_to_uid.get(request.bricklet_number)
        if not uid:
            self.get_logger().warning(
                f"set_rgb_button_color: no button #{request.bricklet_number}"
            )
            response.successful = False
            return response
        # Clamp to valid 0..255 so a program can't pass out-of-range values.
        r = max(0, min(255, request.r))
        g = max(0, min(255, request.g))
        b = max(0, min(255, request.b))
        self.set_button_color(uid, r, g, b)
        self.manual_color_override.add(uid)
        response.successful = True
        return response

    def get_rgb_button_state(
        self, request: GetRgbButtonState.Request, response: GetRgbButtonState.Response
    ) -> GetRgbButtonState.Response:
        uid = self.number_to_uid.get(request.bricklet_number)
        bricklet = self.rgb_led_bricklets.get(uid) if uid else None
        if not bricklet:
            response.successful = False
            response.pressed = False
            return response
        try:
            state = bricklet.get_button_state()
            response.pressed = state == BrickletRGBLEDButton.BUTTON_STATE_PRESSED
            response.successful = True
        except Exception as e:
            self.get_logger().error(f"get_rgb_button_state error: {str(e)}")
            response.successful = False
            response.pressed = False
        return response

    def update_button_colors(self) -> None:
        """Periodically updates button colors based on current program assignments."""
        self.load_button_programs()
        for uid in self.rgb_led_bricklets:
            if uid in self.manual_color_override:
                continue  # a program set this colour explicitly - leave it
            if uid in self.goal_to_uid.values():
                continue  # don't override color while program is running
            if self.uid_to_program.get(uid):
                self.set_button_color(uid, *BLUE_COLOR)
            else:
                self.set_button_color(uid, 0, 0, 0)


def main(args=None):

    rclpy.init(args=args)
    rgb_led_control = RGBButtonControl()
    rclpy.spin(rgb_led_control)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
