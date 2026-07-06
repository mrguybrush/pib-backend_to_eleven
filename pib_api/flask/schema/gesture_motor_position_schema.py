from model.gesture_motor_position_model import GestureMotorPosition
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema
from marshmallow import fields


class GestureMotorPositionSchema(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = GestureMotorPosition
        exclude = ("id",)

    motor_name = fields.Str()


gesture_motor_positions_schema = GestureMotorPositionSchema(
    only=("position", "motor_name"), many=True
)
