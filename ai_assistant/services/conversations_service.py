from __future__ import annotations

import asyncio
import time
from functools import lru_cache
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from ai_assistant.constants import (
    DYNAMODB_MAX_TEXT_FIELD_LENGTH,
    MAX_CONCURRENT_MESSAGE_DELETES,
    MAX_MESSAGES_PER_TRANSACTION,
)
from ai_assistant.exceptions import ConversationAlreadyExistsError, ConversationNotFoundError
from ai_assistant.models import Conversation, DeletionJob, DeletionJobStatus, Message
from ai_assistant.utils.datetime_utils import parse_iso8601_datetime, validate_iso8601_datetime
from config import TTL_DAYS

if TYPE_CHECKING:
    from ai_assistant.clients.conversations_dynamodb import ConversationsDynamoDB


def _ttl_expiry() -> int:
    return int(time.time()) + TTL_DAYS * 24 * 60 * 60


class ConversationsService:
    """Business logic layer for conversations and messages.

    All validation, ordering, TTL management, error translation, and
    cross-table orchestration lives here. The underlying
    :class:`~ai_assistant.clients.conversations_dynamodb.ConversationsDynamoDB`
    client is responsible only for raw DynamoDB operations.
    """

    def __init__(self, client: ConversationsDynamoDB) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    async def get_conversation_by_conversation_id(
        self,
        user_id: str,
        conversation_id: str,
    ) -> Conversation | None:
        item = await self._client.get_conversation_by_conversation_id(user_id, conversation_id)
        return Conversation.from_dynamo(item) if item else None

    async def get_conversations(self, user_id: str) -> list[Conversation]:
        """Return conversations for *user_id* sorted newest-first."""
        items = await self._client.get_conversations(user_id)
        records = [Conversation.from_dynamo(item) for item in items]
        records.sort(key=lambda c: parse_iso8601_datetime(c.last_message_at), reverse=True)
        return records

    async def put_conversation(self, conversation: Conversation) -> dict:
        item = {**conversation.to_dynamo(), "ttl": _ttl_expiry()}
        try:
            return await self._client.put_conversation(item)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConversationAlreadyExistsError(
                    conversation.user_id,
                    conversation.conversation_id,
                ) from e
            raise

    async def update_conversation(
        self,
        user_id: str,
        conversation_id: str,
        last_message_at: str,
        last_message_text: str,
        message_count_delta: int,
    ) -> dict:
        if message_count_delta < 1:
            raise ValueError("message_count_delta must be at least 1")
        if len(last_message_text) > DYNAMODB_MAX_TEXT_FIELD_LENGTH:
            raise ValueError(
                f"last_message_text exceeds {DYNAMODB_MAX_TEXT_FIELD_LENGTH} characters"
            )
        validated_last_message_at = validate_iso8601_datetime(last_message_at)
        try:
            return await self._client.update_conversation(
                user_id,
                conversation_id,
                validated_last_message_at,
                last_message_text,
                message_count_delta,
                _ttl_expiry(),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConversationNotFoundError(user_id, conversation_id) from e
            raise

    # ------------------------------------------------------------------
    # User-data deletion
    # ------------------------------------------------------------------

    async def request_user_data_deletion(self, user_id: str) -> str:
        """Persist a PENDING deletion job with the user's conversation ids.

        Returns the new job id. Does not delete any data.
        """
        conversation_ids = await self._client.get_all_conversation_ids(user_id)
        job = DeletionJob(
            user_id=user_id,
            pending_conversation_ids=conversation_ids,
        )
        await self._client.put_deletion_job(job.to_dynamo())
        return job.job_id

    async def get_deletion_job(self, job_id: str) -> DeletionJob | None:
        item = await self._client.get_deletion_job(job_id)
        return DeletionJob.from_dynamo(item) if item else None

    async def resume_deletion_job(self, job: DeletionJob, owner: str) -> DeletionJob:
        """Run the deletion cascade for *job* and mark it COMPLETE.

        On PENDING jobs, deletes conversation rows first, then message rows per id in
        ``pending_conversation_ids``. Progress writes require *owner* to match
        ``lease_owner``; a mismatch raises :class:`DeletionLeaseLostError`.
        """
        if job.status == DeletionJobStatus.PENDING:
            conversations_deleted = await self._client.delete_conversations_by_ids(
                job.user_id,
                sorted(job.pending_conversation_ids),
            )
            await self._client.set_deletion_job_in_progress(
                job.job_id, conversations_deleted, owner
            )
            job.conversations_deleted = conversations_deleted
            job.status = DeletionJobStatus.IN_PROGRESS

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_MESSAGE_DELETES)

        async def _cascade(conversation_id: str) -> int:
            async with semaphore:
                deleted = await self._client.delete_messages_by_conversation(conversation_id)
                await self._client.checkpoint_conversation_deleted(
                    job.job_id,
                    conversation_id,
                    deleted,
                    owner,
                )
                return deleted

        pending = sorted(job.pending_conversation_ids)
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_cascade(conversation_id)) for conversation_id in pending]

        job.messages_deleted += sum(task.result() for task in tasks)
        job.pending_conversation_ids = set()
        await self._client.finish_deletion_job(job.job_id, DeletionJobStatus.COMPLETE, owner)
        job.status = DeletionJobStatus.COMPLETE
        return job

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def get_messages_by_conversation(
        self,
        conversation_id: str,
        scan_index_forward: bool = False,
    ) -> list[Message]:
        items = await self._client.get_messages_by_conversation(
            conversation_id,
            scan_index_forward=scan_index_forward,
        )
        return [Message.from_dynamo(item) for item in items]

    async def put_messages(self, user_id: str, messages: list[Message]) -> dict:
        if not messages:
            raise ValueError("messages must not be empty")

        conversation_ids = {message.conversation_id for message in messages}
        if len(conversation_ids) != 1:
            raise ValueError("all messages must belong to the same conversation")

        if len(messages) > MAX_MESSAGES_PER_TRANSACTION:
            raise ValueError(
                f"cannot write more than {MAX_MESSAGES_PER_TRANSACTION} messages at once",
            )

        conversation_id = messages[0].conversation_id
        last_message = max(messages, key=lambda m: parse_iso8601_datetime(m.created_at))
        ttl = _ttl_expiry()
        message_items = [{**message.to_dynamo(), "ttl": ttl} for message in messages]

        try:
            return await self._client.put_messages_transaction(
                user_id=user_id,
                conversation_id=conversation_id,
                message_items=message_items,
                last_message_at=last_message.created_at,
                last_message_text=last_message.content,
                message_count=len(messages),
                ttl=ttl,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "TransactionCanceledException":
                reasons = e.response.get("CancellationReasons", [])
                # The client appends the conversation Update as the final
                # TransactItem, so the last CancellationReason corresponds to that
                # Update's condition check.
                if reasons and reasons[-1].get("Code") == "ConditionalCheckFailed":
                    raise ConversationNotFoundError(user_id, conversation_id) from e
            raise


@lru_cache(maxsize=1)
def get_conversations_service() -> ConversationsService:
    from ai_assistant.clients.conversations_dynamodb import get_conversations_dynamodb

    return ConversationsService(get_conversations_dynamodb())
