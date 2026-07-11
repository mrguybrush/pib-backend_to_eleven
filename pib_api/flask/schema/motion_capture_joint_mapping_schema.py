from model.motion_capture_joint_mapping_model import MotionCaptureJointMapping
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema


class MotionCaptureJointMappingSchemaSQLAutoWith(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = MotionCaptureJointMapping
        exclude = ("id",)


motion_capture_joint_mapping_schema = MotionCaptureJointMappingSchemaSQLAutoWith()
motion_capture_joint_mappings_schema = MotionCaptureJointMappingSchemaSQLAutoWith(
    many=True
)
