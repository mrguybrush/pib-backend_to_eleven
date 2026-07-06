from marshmallow import fields

from model.gesture_model import Gesture
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema
from schema.gesture_motor_position_schema import gesture_motor_positions_schema


class GestureSchema(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = Gesture
        exclude = ("id",)

    motor_positions = fields.Nested(gesture_motor_positions_schema)


gestures_schema = GestureSchema(many=True, only=("gesture_id", "name", "deletable"))
gesture_schema = GestureSchema(only=("gesture_id", "name", "motor_positions", "deletable"))
create_gesture_schema = GestureSchema(only=("name", "motor_positions"))
gesture_schema_name_only = GestureSchema(only=("name",))
