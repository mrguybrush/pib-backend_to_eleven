"""Live-Erkennung der angeschlossenen Tinkerforge-Bricklets.

Anders als der Rest der Bricklet-API (die nur die in der DB gespeicherten
UID-Zuweisungen liest/schreibt) fragt dieser Service die tatsaechlich am
HAT steckenden Bricklets ab - inkl. ihrer Steckposition (a-h). Genutzt von
der Hardware-IDs-Seite: eine Tabelle aller erkannten Bricks + die
"Auto-Zuweisung", die die UIDs anhand der Position den DB-Bricklets
zuordnet (siehe hardware-id.component.ts).

Der tinkerforge-Import passiert bewusst LAZY (erst im Funktionsaufruf),
damit die flask-app auch ohne installiertes tinkerforge-Paket startet -
das Paket kommt ueber requirements.txt erst mit dem naechsten Rebuild.
"""
import os
import time

# brickd laeuft auf dem Host; die flask-app erreicht es (wie ros-motors)
# ueber host.docker.internal - siehe docker-compose.yaml (extra_hosts +
# TINKERFORGE_HOST).
TINKERFORGE_HOST = os.getenv("TINKERFORGE_HOST", "host.docker.internal")
TINKERFORGE_PORT = int(os.getenv("TINKERFORGE_PORT", "4223"))

# Wie lange auf die (asynchronen) Enumerations-Callbacks gewartet wird.
_ENUMERATE_WAIT_S = 2.5


def get_detected_bricklets() -> list[dict]:
    """Fragt die angeschlossenen Bricklets live ab und liefert je Bricklet
    {uid, position, deviceType, deviceIdentifier}. Der HAT selbst und
    unbekannte Geraete werden mit deviceType=None zurueckgegeben (die
    Hardware-IDs-Seite kann sie so anzeigen, ordnet sie aber nicht zu)."""
    from tinkerforge.ip_connection import IPConnection
    from tinkerforge.bricklet_servo_v2 import BrickletServoV2
    from tinkerforge.bricklet_solid_state_relay_v2 import (
        BrickletSolidStateRelayV2,
    )
    from tinkerforge.bricklet_rgb_led_button import BrickletRGBLEDButton

    device_type_by_id = {
        BrickletServoV2.DEVICE_IDENTIFIER: "Servo Bricklet",
        BrickletSolidStateRelayV2.DEVICE_IDENTIFIER: "Solid State Relay Bricklet",
        BrickletRGBLEDButton.DEVICE_IDENTIFIER: "RGB LED Button Bricklet",
    }

    detected: dict[str, dict] = {}

    def on_enumerate(
        uid,
        connected_uid,
        position,
        hardware_version,
        firmware_version,
        device_identifier,
        enumeration_type,
    ):
        if enumeration_type == IPConnection.ENUMERATION_TYPE_DISCONNECTED:
            detected.pop(uid, None)
            return
        detected[uid] = {
            "uid": uid,
            "position": position,
            "deviceType": device_type_by_id.get(device_identifier),
            "deviceIdentifier": device_identifier,
        }

    ipcon = IPConnection()
    ipcon.register_callback(IPConnection.CALLBACK_ENUMERATE, on_enumerate)
    ipcon.connect(TINKERFORGE_HOST, TINKERFORGE_PORT)
    try:
        ipcon.enumerate()
        time.sleep(_ENUMERATE_WAIT_S)
    finally:
        ipcon.disconnect()

    # Nach Steckposition sortiert, damit die Tabelle stabil a, b, c, ... ist.
    return sorted(detected.values(), key=lambda b: (b["position"] or "", b["uid"]))
