import pytest
from pydantic import ValidationError

from ai_assistant.constants import DYNAMODB_MAX_TEXT_FIELD_LENGTH
from ai_assistant.models import Message
from tests.constants import MESSAGE_DATA

# ------------------------------------------------------------------
# Message
# ------------------------------------------------------------------


class TestMessage:
    def test_creates_from_valid_data(self):
        msg = Message(**MESSAGE_DATA)

        assert msg.conversation_id == MESSAGE_DATA["conversation_id"]
        assert msg.role == "user"
        assert msg.content == MESSAGE_DATA["content"]

    def test_generates_message_id_when_omitted(self):
        data = {k: v for k, v in MESSAGE_DATA.items() if k != "message_id"}

        msg = Message(**data)

        assert msg.message_id
        assert len(msg.message_id) == 26

    def test_to_dynamo_excludes_none_fields(self):
        msg = Message(**MESSAGE_DATA)

        result = msg.to_dynamo()

        assert "ttl" not in result
        assert "page_url" not in result
        assert "topics" not in result

    def test_to_dynamo_includes_ttl_when_set(self):
        msg = Message(**MESSAGE_DATA, ttl=1_700_000_000)

        result = msg.to_dynamo()

        assert result["ttl"] == 1_700_000_000

    def test_from_dynamo_round_trip(self):
        msg = Message(**MESSAGE_DATA)
        dynamo_item = msg.to_dynamo()

        restored = Message.from_dynamo(dynamo_item)

        assert restored == msg

    def test_rejects_empty_content(self):
        with pytest.raises(ValidationError):
            Message(**{**MESSAGE_DATA, "content": "   "})

    def test_rejects_oversized_content(self):
        with pytest.raises(ValidationError):
            Message(**{**MESSAGE_DATA, "content": "x" * (DYNAMODB_MAX_TEXT_FIELD_LENGTH + 1)})

    def test_rejects_invalid_role(self):
        with pytest.raises(ValidationError):
            Message(**{**MESSAGE_DATA, "role": "system"})

    def test_rejects_invalid_created_at(self):
        with pytest.raises(ValidationError):
            Message(**{**MESSAGE_DATA, "created_at": "not-a-date"})
