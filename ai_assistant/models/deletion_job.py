from enum import StrEnum

from pydantic import BaseModel, Field

from ai_assistant.models.message import new_message_id
from ai_assistant.utils.datetime_utils import utc_now_iso
from ai_assistant.utils.dynamodb import coerce_dynamodb_item


class DeletionJobStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class DeletionJob(BaseModel):
    """DynamoDB record for a user-data deletion job."""

    job_id: str = Field(default_factory=new_message_id)
    user_id: str
    status: DeletionJobStatus = DeletionJobStatus.PENDING
    pending_conversation_ids: set[str] = Field(default_factory=set)
    conversations_deleted: int = 0
    messages_deleted: int = 0
    attempts: int = 0
    lease_owner: str | None = None
    lease_expiry: int | None = None
    last_error: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    ttl: int | None = None

    @classmethod
    def from_dynamo(cls, item: dict) -> "DeletionJob":
        return cls.model_validate(coerce_dynamodb_item(item))

    def to_dynamo(self) -> dict:
        data = self.model_dump(exclude_none=True)
        # DynamoDB rejects empty sets.
        return {
            key: value for key, value in data.items() if not (isinstance(value, set) and not value)
        }
