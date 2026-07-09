from typing import Literal

from pydantic import BaseModel, Field, field_validator
from ulid import ULID

from ai_assistant.constants import DYNAMODB_MAX_TEXT_FIELD_LENGTH
from ai_assistant.utils.datetime_utils import utc_now_iso, validate_iso8601_datetime
from ai_assistant.utils.dynamodb import coerce_dynamodb_item


def new_message_id() -> str:
    return str(ULID())


class Message(BaseModel):
    conversation_id: str
    message_id: str = Field(default_factory=new_message_id)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=DYNAMODB_MAX_TEXT_FIELD_LENGTH)
    created_at: str = Field(default_factory=utc_now_iso)
    page_url: str | None = None
    recommendations_json: list[dict] | None = None
    topics: list[str] | None = None
    followups: list[str] | None = None
    model_name: str | None = None
    model_provider: str | None = None
    guardrail: str | None = None
    ttl: int | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be empty")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_iso8601(cls, value: str) -> str:
        return validate_iso8601_datetime(value)

    @classmethod
    def from_dynamo(cls, item: dict) -> "Message":
        return cls.model_validate(coerce_dynamodb_item(item))

    def to_dynamo(self) -> dict:
        return self.model_dump(exclude_none=True)
