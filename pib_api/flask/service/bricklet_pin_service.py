from typing import Optional

import docker

from app.app import db
from model.bricklet_model import Bricklet
from model.bricklet_pin_model import BrickletPin
from model.defective_pin_model import DefectivePin
from model.motor_model import Motor

# Tinkerforge Servo Bricklet 2.0: 10 servo ports, numbered 0-9.
PINS_PER_SERVO_BRICKLET = 10

# Docker Compose service name (not container name, which also has a
# project-name prefix/replica suffix that can vary) - see docker-compose.yaml.
ROS_MOTORS_SERVICE_NAME = "ros-motors"


def get_pin_grid() -> dict:
    """Every (Servo Bricklet, pin) slot with its assigned motor (if any)
    and defective flag, plus the full motor name list - the frontend
    computes per-row dropdown options from this (a motor already assigned
    to another pin is excluded from the rest)."""
    bricklets = (
        Bricklet.query.filter_by(type="Servo Bricklet")
        .order_by(Bricklet.bricklet_number)
        .all()
    )
    defective_slots = {(dp.bricklet_id, dp.pin) for dp in DefectivePin.query.all()}
    pin_to_motor_name = {
        (bp.bricklet_id, bp.pin): bp.motor.name for bp in BrickletPin.query.all()
    }

    grid = []
    for bricklet in bricklets:
        pins = [
            {
                "pin": pin,
                "motorName": pin_to_motor_name.get((bricklet.id, pin)),
                "defective": (bricklet.id, pin) in defective_slots,
            }
            for pin in range(PINS_PER_SERVO_BRICKLET)
        ]
        grid.append(
            {
                "brickletId": bricklet.id,
                "brickletNumber": bricklet.bricklet_number,
                "uid": bricklet.uid,
                "pins": pins,
            }
        )

    all_motor_names = [m.name for m in Motor.query.order_by(Motor.name).all()]
    return {"bricklets": grid, "allMotorNames": all_motor_names}


def assign_pin(bricklet_id: int, pin: int, motor_name: Optional[str]) -> None:
    existing = BrickletPin.query.filter_by(bricklet_id=bricklet_id, pin=pin).first()

    if not motor_name:
        if existing:
            db.session.delete(existing)
            db.session.flush()
        return

    if DefectivePin.query.filter_by(bricklet_id=bricklet_id, pin=pin).first():
        raise ValueError("Dieser Pin ist als defekt markiert.")

    motor = Motor.query.filter_by(name=motor_name).one()

    # A motor can only ever live at one physical pin - defensively enforced
    # here even though the frontend already excludes motors assigned
    # elsewhere from a pin's dropdown options.
    conflicting = BrickletPin.query.filter(
        BrickletPin.motor_id == motor.id,
        db.or_(
            BrickletPin.bricklet_id != bricklet_id, BrickletPin.pin != pin
        ),
    ).first()
    if conflicting:
        raise ValueError(
            f"Motor '{motor_name}' ist bereits einem anderen Pin zugewiesen."
        )

    if existing:
        existing.motor_id = motor.id
    else:
        db.session.add(
            BrickletPin(
                motor_id=motor.id, bricklet_id=bricklet_id, pin=pin, invert=False
            )
        )
    db.session.flush()


def set_pin_defective(bricklet_id: int, pin: int, defective: bool) -> None:
    if defective and BrickletPin.query.filter_by(
        bricklet_id=bricklet_id, pin=pin
    ).first():
        raise ValueError(
            "Pin ist noch einem Körperteil zugewiesen - zuerst auf "
            "'nicht angeschlossen' setzen."
        )

    row = DefectivePin.query.filter_by(bricklet_id=bricklet_id, pin=pin).first()
    if defective and not row:
        db.session.add(DefectivePin(bricklet_id=bricklet_id, pin=pin))
        db.session.flush()
    elif not defective and row:
        db.session.delete(row)
        db.session.flush()


def restart_motors_container() -> None:
    """Restarts the ros-motors container so it re-reads the pin/motor
    wiring (and motor settings) from the DB - it only loads that once at
    startup. Needs /var/run/docker.sock mounted into this container (see
    docker-compose.yaml); the API only ever exposes this one specific
    action, never arbitrary container control."""
    client = docker.from_env()
    containers = client.containers.list(
        filters={"label": f"com.docker.compose.service={ROS_MOTORS_SERVICE_NAME}"}
    )
    if not containers:
        raise ValueError(f"Container für Service '{ROS_MOTORS_SERVICE_NAME}' nicht gefunden.")
    containers[0].restart(timeout=10)
