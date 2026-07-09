from pydantic import BaseModel, Field, field_validator

from ai_assistant.constants import (
    DYNAMODB_MAX_TEXT_FIELD_LENGTH,
    DYNAMODB_MAX_TITLE_LENGTH,
)
from ai_assistant.utils.datetime_utils import utc_now_iso, validate_iso8601_datetime
from ai_assistant.utils.dynamodb import coerce_dynamodb_item


class Conversation(BaseModel):
    user_id: str
    conversation_id: str
    site_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    last_message_at: str
    title: str = Field(max_length=DYNAMODB_MAX_TITLE_LENGTH)
    last_message_text: str = Field(max_length=DYNAMODB_MAX_TEXT_FIELD_LENGTH)
    message_count: int = 0
    ttl: int | None = None

    @field_validator("created_at", "last_message_at")
    @classmethod
    def timestamps_must_be_iso8601(cls, value: str) -> str:
        return validate_iso8601_datetime(value)

    @classmethod
    def from_dynamo(cls, item: dict) -> "Conversation":
        return cls.model_validate(coerce_dynamodb_item(item))

    def to_dynamo(self) -> dict:
        return self.model_dump(exclude_none=True)
