from model.motion_capture_settings_model import MotionCaptureSettings
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema


class MotionCaptureSettingsSchemaSQLAutoWith(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = MotionCaptureSettings


motion_capture_settings_schema = MotionCaptureSettingsSchemaSQLAutoWith(exclude=("id",))
