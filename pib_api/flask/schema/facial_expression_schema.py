from model.facial_expression_model import FacialExpression
from schema.sql_auto_with_camel_case_schema import SQLAutoWithCamelCaseSchema


class FacialExpressionSchema(SQLAutoWithCamelCaseSchema):
    class Meta:
        model = FacialExpression
        exclude = ("id",)


facial_expressions_schema = FacialExpressionSchema(
    many=True, only=("expression_id", "name")
)
facial_expression_schema = FacialExpressionSchema(only=("expression_id", "name"))
facial_expression_schema_name_only = FacialExpressionSchema(only=("name",))
