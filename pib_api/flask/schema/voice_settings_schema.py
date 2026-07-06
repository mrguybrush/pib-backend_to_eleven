from model.voice_settings_model import VoiceSettings
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema


class VoiceSettingsSchemaSQLAutoWith(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = VoiceSettings


voice_settings_schema = VoiceSettingsSchemaSQLAutoWith(exclude=("id",))
