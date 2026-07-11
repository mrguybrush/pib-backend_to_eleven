from model.llm_settings_model import LlmSettings
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema


class LlmSettingsSchemaSQLAutoWith(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = LlmSettings


llm_settings_schema = LlmSettingsSchemaSQLAutoWith(exclude=("id",))
