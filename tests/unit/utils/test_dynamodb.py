from decimal import Decimal

from ai_assistant.utils.dynamodb import coerce_dynamodb_item

# ------------------------------------------------------------------
# coerce_dynamodb_item
# ------------------------------------------------------------------


class TestCoerceDynamodbItem:
    def test_converts_decimal_to_int(self):
        item = {"count": Decimal("5")}

        result = coerce_dynamodb_item(item)

        assert result["count"] == 5
        assert isinstance(result["count"], int)

    def test_converts_decimal_to_float(self):
        item = {"score": Decimal("1.5")}

        result = coerce_dynamodb_item(item)

        assert result["score"] == 1.5
        assert isinstance(result["score"], float)

    def test_handles_nested_dict(self):
        item = {"meta": {"count": Decimal("3")}}

        result = coerce_dynamodb_item(item)

        assert result["meta"]["count"] == 3

    def test_handles_list_of_decimals(self):
        item = {"nums": [Decimal("1"), Decimal("2")]}

        result = coerce_dynamodb_item(item)

        assert result["nums"] == [1, 2]

    def test_handles_list_of_dicts_with_decimals(self):
        # Mirrors the shape of DynamoDB list attributes containing nested objects.
        item = {"records": [{"count": Decimal("4"), "score": Decimal("1.5")}]}

        result = coerce_dynamodb_item(item)

        assert result["records"] == [{"count": 4, "score": 1.5}]
        assert isinstance(result["records"][0]["count"], int)
        assert isinstance(result["records"][0]["score"], float)

    def test_passes_through_non_decimal_types_unchanged(self):
        # str, bool, int, and None must survive coercion untouched.
        item = {"name": "Alice", "active": True, "score": 42, "note": None}

        result = coerce_dynamodb_item(item)

        assert result == item
        assert isinstance(result["name"], str)
        assert isinstance(result["active"], bool)
        assert isinstance(result["score"], int)
        assert result["note"] is None
