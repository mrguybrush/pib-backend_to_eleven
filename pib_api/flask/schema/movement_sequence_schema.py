from marshmallow import fields

from model.movement_sequence_model import MovementSequence
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema
from schema.movement_sequence_frame_schema import (
    movement_sequence_frames_schema,
    movement_sequence_frames_create_schema,
)


class MovementSequenceSchema(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = MovementSequence
        exclude = ("id",)

    frames = fields.Nested(movement_sequence_frames_schema)


class MovementSequenceCreateSchema(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = MovementSequence
        exclude = ("id",)

    frames = fields.Nested(movement_sequence_frames_create_schema)


movement_sequences_schema = MovementSequenceSchema(
    many=True, only=("sequence_id", "name", "deletable", "sample_rate_hz")
)
movement_sequence_schema = MovementSequenceSchema(
    only=("sequence_id", "name", "deletable", "sample_rate_hz", "frames")
)
create_movement_sequence_schema = MovementSequenceCreateSchema(
    only=("name", "sample_rate_hz", "frames")
)
movement_sequence_schema_name_only = MovementSequenceSchema(only=("name",))
