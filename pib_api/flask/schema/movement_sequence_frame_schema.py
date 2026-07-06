from marshmallow import fields

from model.movement_sequence_frame_model import MovementSequenceFrame
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema


class MovementSequenceFrameSchema(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = MovementSequenceFrame
        exclude = ("id",)

    # frame_index is assigned server-side (by position in the list), never
    # supplied by the client - dump_only so it's absent from load validation
    frame_index = fields.Int(dump_only=True)
    positions = fields.Dict(keys=fields.Str(), values=fields.Int())


movement_sequence_frames_schema = MovementSequenceFrameSchema(
    only=("frame_index", "timestamp_ms", "positions"), many=True
)
# Used only for validating client-supplied frames on creation (no frame_index)
movement_sequence_frames_create_schema = MovementSequenceFrameSchema(
    only=("timestamp_ms", "positions"), many=True
)
