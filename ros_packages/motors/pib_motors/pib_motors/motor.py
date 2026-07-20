from typing import Any
from pib_motors.bricklet_pin import BrickletPin
from pib_api_client import motor_client


class Motor:

    MIN_ROTATION: int = -9000
    MAX_ROTATION: int = 9000

    NO_CURRENT: int = BrickletPin.NO_CURRENT

    # Global "Bewegungstempo" (10-100), shared by every Motor instance - see
    # set_movement_speed_percent().
    movement_speed_percent: int = 100

    def __init__(
        self,
        name: str,
        bricklet_pins: list[BrickletPin],
        invert: bool,
        velocity: int = 0,
        acceleration: int = 0,
        deceleration: int = 0,
    ):
        self.name: str = name
        self.visible: bool = True
        self.bricklet_pins: list[BrickletPin] = bricklet_pins
        self.invert: bool = invert
        self.rotation_range_min: int = Motor.MIN_ROTATION
        self.rotation_range_max: int = Motor.MAX_ROTATION
        # This motor's OWN configured motion values (the "100%" baseline),
        # loaded once at startup from the DB (see the module-level init
        # loop below). Kept reliably in memory so the global movement-speed
        # can be scaled off them without any per-move HTTP round-trip - a
        # zero/stale baseline would scale to 0, which the Servo Bricklet
        # reads as "no speed limit" (i.e. full speed), the exact opposite of
        # what a low percentage should do.
        self.velocity: int = velocity
        self.acceleration: int = acceleration
        self.deceleration: int = deceleration
        # Which movement_speed_percent this motor's bricklet-pins were last
        # configured for. None forces a fresh scaled write on the next move.
        self._last_written_speed_percent: int | None = None

    @classmethod
    def set_movement_speed_percent(cls, percent: int) -> None:
        """Sets the global movement speed. Intentionally cheap: it only
        updates the shared percentage and lets each motor lazily re-apply
        its scaled velocity/acceleration/deceleration on its NEXT move (see
        set_position -> _ensure_scaled_motion_config). This keeps the
        apply_movement_settings ROS-service callback fast - writing the
        scaled config to all ~30 bricklet-pins over the network *inside* the
        single-threaded ROS callback made it so slow that the service
        response timed out and rapid slider changes backed up."""
        cls.movement_speed_percent = percent

    def __str__(self):
        return f"MOTOR[ bricklet_pins: {[str(bp) for bp in self.bricklet_pins]}, settings: {self.get_settings()} ]"

    def apply_settings(self, settings_dto: dict[str, Any]) -> bool:
        """apply provided settings to the motor"""
        self.visible = settings_dto["visible"]
        self.invert = settings_dto["invert"]
        self.rotation_range_min = settings_dto["rotationRangeMin"]
        self.rotation_range_max = settings_dto["rotationRangeMax"]
        # Keep the in-memory baseline in sync with the newly saved values,
        # and force the next move to re-write the (scaled) motion config -
        # bp.apply_settings() below writes the UNSCALED values straight to
        # the bricklet, so if a speed other than 100% is active it must be
        # rescaled before the motor next moves.
        self.velocity = settings_dto["velocity"]
        self.acceleration = settings_dto["acceleration"]
        self.deceleration = settings_dto["deceleration"]
        self._last_written_speed_percent = None

        if not self.bricklet_pins:
            return False

        # Check if current position is outside of new rotation Ranges
        adjusted_position = self._validate_position(self.get_position())
        if adjusted_position != self.get_position():
            self.set_position(adjusted_position)

        return all(bp.apply_settings(settings_dto) for bp in self.bricklet_pins)

    def _ensure_scaled_motion_config(self) -> None:
        """Writes this motor's velocity/acceleration/deceleration to its
        bricklet-pin(s), scaled by the global movement_speed_percent - but
        only when that percentage changed since the last write, so a move at
        a steady speed costs no extra bricklet round-trip."""
        if self._last_written_speed_percent == Motor.movement_speed_percent:
            return
        factor = Motor.movement_speed_percent / 100
        scaled_settings = {
            "velocity": round(self.velocity * factor),
            "acceleration": round(self.acceleration * factor),
            "deceleration": round(self.deceleration * factor),
        }
        for bp in self.bricklet_pins:
            bp.set_motion_configuration(scaled_settings)
        self._last_written_speed_percent = Motor.movement_speed_percent

    def get_settings(self) -> dict[str, Any]:
        """get the current settings of this motor"""
        settings = {
            "visible": self.visible,
            "name": self.name,
            "invert": self.invert,
            "rotationRangeMin": self.rotation_range_min,
            "rotationRangeMax": self.rotation_range_max,
        }
        if not self.bricklet_pins:
            return settings
        settings.update(self.bricklet_pins[0].get_settings())
        return settings

    def set_position(self, position: int) -> bool:
        """sets the position of all bricklet-pins associated with this motor"""
        if not self.bricklet_pins:
            return False
        if self.invert:
            position *= -1
        position = self._validate_position(position)
        # Apply the global movement-speed scaling just before moving (cheap
        # no-op unless the speed changed since this motor last moved).
        self._ensure_scaled_motion_config()
        return all(bp.set_position(position) for bp in self.bricklet_pins)

    def get_position(self) -> int:
        """returns the target position of the motor as set by the last command, or '0' if no bricklet-pin is connected"""
        if not self.bricklet_pins:
            return 0
        return self.bricklet_pins[0].get_position()

    def get_current_position(self) -> int:
        """returns the actual physical position of the motor at this moment, or '0' if no bricklet-pin is connected"""
        if not self.bricklet_pins:
            return 0
        return self.bricklet_pins[0].get_current_position()

    def has_reached_position(self) -> bool:
        """returns 'True' if all bricklet-pins of this motor have reached their target position"""
        if not self.bricklet_pins:
            return True
        return all(bp.has_reached_target() for bp in self.bricklet_pins)

    def get_current(self) -> int:
        """returns the maximum current of all bricklet-pins, or NO_CURRENT, if not bricklet-pin is connected"""
        if not self.bricklet_pins:
            return Motor.NO_CURRENT
        return max(bp.get_current() for bp in self.bricklet_pins)

    def check_if_motor_is_connected(self) -> bool:
        """returns 'True' if all bricklet-pins of this motor are connected"""
        return bool(self.bricklet_pins) and all(
            bp.is_connected() for bp in self.bricklet_pins
        )

    def _validate_position(self, position: int) -> int:
        """Check if position is within range, set it to the min/max value if not."""
        position = min(max(position, self.rotation_range_min), self.rotation_range_max)
        return position


# get data from pib-api
successful, response = motor_client.get_all_motors()
if not successful:
    raise RuntimeError("failed to load motors from pib-api...")

# list of all available motor-objects
motors: list[Motor] = []
for motor_dto in response["motors"]:
    bricklet_pins = [
        BrickletPin(
            bricklet_pin_dto["pin"],
            bricklet_pin_dto["bricklet"],
            bricklet_pin_dto["invert"],
        )
        for bricklet_pin_dto in motor_dto["brickletPins"]
        if bricklet_pin_dto["bricklet"]
    ]
    motors.append(
        Motor(
            motor_dto["name"],
            bricklet_pins,
            motor_dto["invert"],
            velocity=motor_dto["velocity"],
            acceleration=motor_dto["acceleration"],
            deceleration=motor_dto["deceleration"],
        )
    )

# maps the name of a (multi-)motor to its associated motor objects
name_to_motors: dict[str, Motor] = {motor.name: [motor] for motor in motors}
name_to_motors["all_fingers_left"] = [
    motor for motor in motors if motor.name.endswith("left_stretch")
]
name_to_motors["all_fingers_right"] = [
    motor for motor in motors if motor.name.endswith("right_stretch")
]
