from decimal import Decimal
from typing import Any


def _coerce_dynamodb_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {key: _coerce_dynamodb_value(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_coerce_dynamodb_value(nested) for nested in value]
    if isinstance(value, set):
        return {_coerce_dynamodb_value(nested) for nested in value}
    return value


def coerce_dynamodb_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize boto3 DynamoDB types for Pydantic validation."""
    return {key: _coerce_dynamodb_value(value) for key, value in item.items()}
