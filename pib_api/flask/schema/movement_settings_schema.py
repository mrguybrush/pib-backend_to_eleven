from model.movement_settings_model import MovementSettings
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema


class MovementSettingsSchemaSQLAutoWith(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = MovementSettings


movement_settings_schema = MovementSettingsSchemaSQLAutoWith(exclude=("id",))
