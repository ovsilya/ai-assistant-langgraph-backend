from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.constants import (
    DYNAMODB_MAX_TEXT_FIELD_LENGTH,
    DYNAMODB_MAX_TITLE_LENGTH,
)
from ai_assistant.models import Conversation
from tests.constants import CONVERSATION_DATA

# ------------------------------------------------------------------
# Conversation
# ------------------------------------------------------------------


class TestConversation:
    def test_creates_from_valid_data(self):
        conv = Conversation(**CONVERSATION_DATA)

        assert conv.user_id == CONVERSATION_DATA["user_id"]
        assert conv.conversation_id == CONVERSATION_DATA["conversation_id"]
        assert conv.message_count == 0

    def test_default_created_at(self):
        before = datetime.now(UTC)
        conv = Conversation(
            user_id=CONVERSATION_DATA["user_id"],
            conversation_id=CONVERSATION_DATA["conversation_id"],
            site_id=CONVERSATION_DATA["site_id"],
            title=CONVERSATION_DATA["title"],
            last_message_text=CONVERSATION_DATA["last_message_text"],
            last_message_at=CONVERSATION_DATA["last_message_at"],
        )
        after = datetime.now(UTC)

        created = datetime.fromisoformat(conv.created_at)
        assert before <= created <= after

    def test_to_dynamo_excludes_none_ttl(self):
        conv = Conversation(**CONVERSATION_DATA)

        result = conv.to_dynamo()

        assert "ttl" not in result

    def test_to_dynamo_includes_ttl_when_set(self):
        conv = Conversation(**CONVERSATION_DATA, ttl=1_700_000_000)

        result = conv.to_dynamo()

        assert result["ttl"] == 1_700_000_000

    def test_from_dynamo_round_trip(self):
        conv = Conversation(**CONVERSATION_DATA)
        dynamo_item = conv.to_dynamo()

        restored = Conversation.from_dynamo(dynamo_item)

        assert restored == conv

    def test_rejects_invalid_created_at(self):
        with pytest.raises(ValidationError):
            Conversation(**{**CONVERSATION_DATA, "created_at": "not-a-date"})

    def test_rejects_invalid_last_message_at(self):
        with pytest.raises(ValidationError):
            Conversation(**{**CONVERSATION_DATA, "last_message_at": "not-a-date"})

    def test_rejects_oversized_title(self):
        with pytest.raises(ValidationError):
            Conversation(**{**CONVERSATION_DATA, "title": "x" * (DYNAMODB_MAX_TITLE_LENGTH + 1)})

    def test_rejects_oversized_last_message_text(self):
        with pytest.raises(ValidationError):
            Conversation(
                **{
                    **CONVERSATION_DATA,
                    "last_message_text": "x" * (DYNAMODB_MAX_TEXT_FIELD_LENGTH + 1),
                }
            )
