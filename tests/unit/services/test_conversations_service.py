from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError

from ai_assistant.constants import (
    DYNAMODB_MAX_TEXT_FIELD_LENGTH,
    MAX_MESSAGES_PER_TRANSACTION,
)
from ai_assistant.exceptions import ConversationAlreadyExistsError, ConversationNotFoundError
from ai_assistant.models import Conversation, DeletionJob, DeletionJobStatus, Message
from ai_assistant.services.conversations_service import ConversationsService
from tests.constants import (
    CONVERSATION_DATA,
    CONVERSATION_ID,
    CONVERSATION_ITEM,
    EXPECTED_TTL,
    MESSAGE_INPUT,
    MESSAGE_ITEM,
    MOCK_TIME,
    SUCCESSFUL_RESPONSE,
    USER_ID,
    _client_error,
    _transaction_canceled_error,
)

MODULE = "ai_assistant.services.conversations_service"


def _make_client() -> AsyncMock:
    """Return an AsyncMock standing in for ConversationsDynamoDB."""
    client = AsyncMock()
    client.conversations_table = "conversations"
    client.messages_table = "messages"
    return client


# ------------------------------------------------------------------
# get_conversation_by_conversation_id
# ------------------------------------------------------------------


class TestGetConversationByConversationId:
    async def test_returns_conversation_when_found(self):
        client = _make_client()
        client.get_conversation_by_conversation_id.return_value = CONVERSATION_ITEM
        service = ConversationsService(client)

        result = await service.get_conversation_by_conversation_id(USER_ID, CONVERSATION_ID)

        assert isinstance(result, Conversation)
        assert result.user_id == USER_ID
        assert result.conversation_id == CONVERSATION_ID

    async def test_returns_none_when_not_found(self):
        client = _make_client()
        client.get_conversation_by_conversation_id.return_value = None
        service = ConversationsService(client)

        result = await service.get_conversation_by_conversation_id(USER_ID, CONVERSATION_ID)

        assert result is None


# ------------------------------------------------------------------
# get_conversations — sorted newest-first, model conversion
# ------------------------------------------------------------------


class TestGetConversations:
    async def test_converts_raw_dicts_to_conversation_models(self):
        client = _make_client()
        client.get_conversations.return_value = [CONVERSATION_ITEM]
        service = ConversationsService(client)

        results = await service.get_conversations(USER_ID)

        assert len(results) == 1
        assert isinstance(results[0], Conversation)
        assert results[0].user_id == USER_ID

    async def test_sorts_by_parsed_datetime_not_lexicographic_order(self):
        # These two timestamps diverge between lexicographic and UTC ordering:
        #   utc_midnight  = 2026-12-01 00:00 UTC  (later in real time)
        #   ahead_of_utc  = 2026-12-01 06:00 UTC+7 = 2026-11-30 23:00 UTC (earlier in real time)
        # Lexicographically "06" > "00", so a naive string sort would put ahead_of_utc first.
        # The service must use parse_iso8601_datetime to get the correct UTC order.
        utc_midnight_item = {
            **CONVERSATION_ITEM,
            "conversation_id": "conv_utc_midnight",
            "last_message_at": "2026-12-01T00:00:00+00:00",
        }
        ahead_of_utc_item = {
            **CONVERSATION_ITEM,
            "conversation_id": "conv_ahead_of_utc",
            "last_message_at": "2026-12-01T06:00:00+07:00",
        }
        client = _make_client()
        client.get_conversations.return_value = [utc_midnight_item, ahead_of_utc_item]

        service = ConversationsService(client)
        results = await service.get_conversations(USER_ID)

        # utc_midnight (Dec 1 00:00 UTC) is later than ahead_of_utc (Nov 30 23:00 UTC).
        assert results[0].conversation_id == "conv_utc_midnight"
        assert results[1].conversation_id == "conv_ahead_of_utc"


# ------------------------------------------------------------------
# put_conversation — TTL injection, error translation
# ------------------------------------------------------------------


class TestPutConversation:
    @patch(f"{MODULE}.time.time", return_value=MOCK_TIME)
    async def test_injects_ttl_and_serializes_model(self, _mock_time):
        client = _make_client()
        client.put_conversation.return_value = SUCCESSFUL_RESPONSE
        service = ConversationsService(client)
        conversation = Conversation(**CONVERSATION_DATA)

        await service.put_conversation(conversation)

        call_item = client.put_conversation.call_args.args[0]
        assert call_item["ttl"] == EXPECTED_TTL
        assert call_item["user_id"] == USER_ID
        assert call_item["conversation_id"] == CONVERSATION_ID

    @patch(f"{MODULE}.time.time", return_value=MOCK_TIME)
    async def test_translates_conditional_check_to_already_exists(self, _mock_time):
        client = _make_client()
        client.put_conversation.side_effect = _client_error(
            "ConditionalCheckFailedException", "PutItem"
        )
        service = ConversationsService(client)

        with pytest.raises(ConversationAlreadyExistsError) as exc_info:
            await service.put_conversation(Conversation(**CONVERSATION_DATA))
        assert exc_info.value.user_id == USER_ID
        assert exc_info.value.conversation_id == CONVERSATION_ID

    async def test_reraises_unrelated_client_errors(self):
        client = _make_client()
        client.put_conversation.side_effect = _client_error(
            "ProvisionedThroughputExceededException", "PutItem"
        )
        service = ConversationsService(client)

        with pytest.raises(ClientError) as exc_info:
            await service.put_conversation(Conversation(**CONVERSATION_DATA))
        assert exc_info.value.response["Error"]["Code"] == "ProvisionedThroughputExceededException"


# ------------------------------------------------------------------
# update_conversation — input validation, TTL injection, error translation
# ------------------------------------------------------------------


class TestUpdateConversation:
    @pytest.mark.parametrize("message_count_delta", [0, -1])
    async def test_rejects_nonpositive_message_count_delta(self, message_count_delta):
        service = ConversationsService(_make_client())

        with pytest.raises(ValueError, match="at least 1"):
            await service.update_conversation(
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                last_message_at="2026-01-02T00:00:00+00:00",
                last_message_text="Hello",
                message_count_delta=message_count_delta,
            )

    async def test_rejects_invalid_last_message_at(self):
        service = ConversationsService(_make_client())

        with pytest.raises(ValueError, match="ISO 8601"):
            await service.update_conversation(
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                last_message_at="not-a-date",
                last_message_text="Hello",
                message_count_delta=1,
            )

    async def test_rejects_oversized_last_message_text(self):
        service = ConversationsService(_make_client())

        with pytest.raises(ValueError, match="last_message_text exceeds"):
            await service.update_conversation(
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                last_message_at="2026-01-02T00:00:00+00:00",
                last_message_text="x" * (DYNAMODB_MAX_TEXT_FIELD_LENGTH + 1),
                message_count_delta=1,
            )

    @patch(f"{MODULE}.time.time", return_value=MOCK_TIME)
    async def test_passes_ttl_and_validated_datetime_to_client(self, _mock_time):
        client = _make_client()
        client.update_conversation.return_value = SUCCESSFUL_RESPONSE
        service = ConversationsService(client)

        await service.update_conversation(
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            last_message_at="2026-01-02T00:00:00+00:00",
            last_message_text="Hello",
            message_count_delta=2,
        )

        client.update_conversation.assert_awaited_once_with(
            USER_ID,
            CONVERSATION_ID,
            "2026-01-02T00:00:00+00:00",
            "Hello",
            2,
            EXPECTED_TTL,
        )

    @patch(f"{MODULE}.time.time", return_value=MOCK_TIME)
    async def test_translates_conditional_check_to_not_found(self, _mock_time):
        client = _make_client()
        client.update_conversation.side_effect = _client_error(
            "ConditionalCheckFailedException", "UpdateItem"
        )
        service = ConversationsService(client)

        with pytest.raises(ConversationNotFoundError) as exc_info:
            await service.update_conversation(
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                last_message_at="2026-01-02T00:00:00+00:00",
                last_message_text="Hello",
                message_count_delta=1,
            )
        assert exc_info.value.user_id == USER_ID
        assert exc_info.value.conversation_id == CONVERSATION_ID


# ------------------------------------------------------------------
# request_user_data_deletion / resume_deletion_job / get_deletion_job
# ------------------------------------------------------------------


class TestRequestUserDataDeletion:
    async def test_records_job_with_captured_ids_before_any_delete(self):
        client = _make_client()
        client.get_all_conversation_ids.return_value = {CONVERSATION_ID, "conv_two"}
        service = ConversationsService(client)

        job_id = await service.request_user_data_deletion(USER_ID)

        assert len(job_id) == 26
        item = client.put_deletion_job.call_args.args[0]
        assert item["user_id"] == USER_ID
        assert item["status"] == DeletionJobStatus.PENDING.value
        assert item["pending_conversation_ids"] == {CONVERSATION_ID, "conv_two"}
        assert "ttl" not in item
        client.delete_conversations_by_ids.assert_not_called()
        client.delete_messages_by_conversation.assert_not_called()

    async def test_records_job_when_user_has_no_conversations(self):
        client = _make_client()
        client.get_all_conversation_ids.return_value = set()
        service = ConversationsService(client)

        await service.request_user_data_deletion(USER_ID)

        item = client.put_deletion_job.call_args.args[0]
        assert "pending_conversation_ids" not in item


class TestResumeDeletionJob:
    async def test_pending_job_deletes_conversations_then_cascades(self):
        client = _make_client()
        client.delete_conversations_by_ids.return_value = 2
        client.delete_messages_by_conversation.side_effect = [3, 4]
        service = ConversationsService(client)
        job = DeletionJob(user_id=USER_ID, pending_conversation_ids={"c1", "c2"})

        result = await service.resume_deletion_job(job, owner="w1")

        client.delete_conversations_by_ids.assert_awaited_once_with(USER_ID, ["c1", "c2"])
        client.set_deletion_job_in_progress.assert_awaited_once_with(job.job_id, 2, "w1")
        assert client.delete_messages_by_conversation.await_count == 2
        assert client.checkpoint_conversation_deleted.await_count == 2
        client.finish_deletion_job.assert_awaited_once_with(
            job.job_id, DeletionJobStatus.COMPLETE, "w1"
        )
        assert result.status == DeletionJobStatus.COMPLETE
        assert result.conversations_deleted == 2
        assert result.messages_deleted == 7
        assert result.pending_conversation_ids == set()

    async def test_in_progress_job_skips_conversation_delete(self):
        client = _make_client()
        client.delete_messages_by_conversation.return_value = 5
        service = ConversationsService(client)
        job = DeletionJob(
            user_id=USER_ID,
            status=DeletionJobStatus.IN_PROGRESS,
            pending_conversation_ids={"c2"},
            conversations_deleted=2,
            messages_deleted=3,
        )

        result = await service.resume_deletion_job(job, owner="w1")

        client.delete_conversations_by_ids.assert_not_called()
        client.set_deletion_job_in_progress.assert_not_called()
        client.checkpoint_conversation_deleted.assert_awaited_once()
        assert result.messages_deleted == 8
        assert result.status == DeletionJobStatus.COMPLETE

    async def test_does_not_finish_when_a_cascade_fails(self):
        client = _make_client()
        client.delete_messages_by_conversation.side_effect = RuntimeError("boom")
        service = ConversationsService(client)
        job = DeletionJob(
            user_id=USER_ID,
            status=DeletionJobStatus.IN_PROGRESS,
            pending_conversation_ids={"c1"},
        )

        with pytest.raises(ExceptionGroup):
            await service.resume_deletion_job(job, owner="w1")
        client.finish_deletion_job.assert_not_called()

    async def test_pending_job_with_no_conversations_completes(self):
        client = _make_client()
        client.delete_conversations_by_ids.return_value = 0
        service = ConversationsService(client)
        job = DeletionJob(user_id=USER_ID)

        result = await service.resume_deletion_job(job, owner="w1")

        client.set_deletion_job_in_progress.assert_awaited_once_with(job.job_id, 0, "w1")
        client.delete_messages_by_conversation.assert_not_called()
        client.finish_deletion_job.assert_awaited_once_with(
            job.job_id, DeletionJobStatus.COMPLETE, "w1"
        )
        assert result.status == DeletionJobStatus.COMPLETE
        assert result.messages_deleted == 0


class TestGetDeletionJob:
    async def test_returns_model_when_found(self):
        client = _make_client()
        client.get_deletion_job.return_value = DeletionJob(
            user_id=USER_ID, pending_conversation_ids={"c1"}
        ).to_dynamo()
        service = ConversationsService(client)

        result = await service.get_deletion_job("j1")

        assert isinstance(result, DeletionJob)
        assert result.user_id == USER_ID

    async def test_returns_none_when_missing(self):
        client = _make_client()
        client.get_deletion_job.return_value = None
        service = ConversationsService(client)

        assert await service.get_deletion_job("j1") is None


# ------------------------------------------------------------------
# get_messages_by_conversation — model conversion
# ------------------------------------------------------------------


class TestGetMessagesByConversation:
    async def test_converts_raw_dicts_to_message_models(self):
        client = _make_client()
        client.get_messages_by_conversation.return_value = [MESSAGE_ITEM]
        service = ConversationsService(client)

        results = await service.get_messages_by_conversation(CONVERSATION_ID)

        assert len(results) == 1
        assert isinstance(results[0], Message)
        assert results[0].conversation_id == CONVERSATION_ID

    async def test_passes_scan_index_forward(self):
        client = _make_client()
        client.get_messages_by_conversation.return_value = []
        service = ConversationsService(client)

        await service.get_messages_by_conversation(CONVERSATION_ID, scan_index_forward=True)

        client.get_messages_by_conversation.assert_awaited_once_with(
            CONVERSATION_ID, scan_index_forward=True
        )


# ------------------------------------------------------------------
# put_messages — validation, TTL, transaction building, error translation
# ------------------------------------------------------------------


class TestPutMessages:
    async def test_empty_list_raises(self):
        service = ConversationsService(_make_client())

        with pytest.raises(ValueError, match="empty"):
            await service.put_messages(USER_ID, [])

    async def test_multiple_conversations_raises(self):
        service = ConversationsService(_make_client())
        messages = [
            Message(**MESSAGE_INPUT),
            Message(**{**MESSAGE_INPUT, "conversation_id": "conv_other"}),
        ]

        with pytest.raises(ValueError, match="same conversation"):
            await service.put_messages(USER_ID, messages)

    async def test_rejects_batches_over_transaction_limit(self):
        service = ConversationsService(_make_client())
        messages = [
            Message(**{**MESSAGE_INPUT, "message_id": f"msg_{index:022d}"})
            for index in range(MAX_MESSAGES_PER_TRANSACTION + 1)
        ]

        with pytest.raises(ValueError, match=f"{MAX_MESSAGES_PER_TRANSACTION} messages"):
            await service.put_messages(USER_ID, messages)

    @patch(f"{MODULE}.time.time", return_value=MOCK_TIME)
    async def test_passes_ttl_and_correct_last_message_to_client(self, _mock_time):
        client = _make_client()
        client.put_messages_transaction.return_value = SUCCESSFUL_RESPONSE
        service = ConversationsService(client)

        user_message = Message(**MESSAGE_INPUT)
        assistant_message = Message(
            **{
                **MESSAGE_INPUT,
                "message_id": "01JYYYYYYYYYYYYYYYYYYYYYYYYY",
                "role": "assistant",
                "content": "Sunny and 72F.",
                "created_at": "2026-01-03T00:00:00+00:00",
            }
        )

        response = await service.put_messages(USER_ID, [user_message, assistant_message])

        kwargs = client.put_messages_transaction.call_args.kwargs

        # Each serialized message carries the TTL.
        message_items = kwargs["message_items"]
        assert [item["message_id"] for item in message_items] == [
            user_message.message_id,
            assistant_message.message_id,
        ]
        assert all(item["ttl"] == EXPECTED_TTL for item in message_items)

        # Conversation metadata uses the latest message (assistant, later timestamp).
        assert kwargs["user_id"] == USER_ID
        assert kwargs["conversation_id"] == CONVERSATION_ID
        assert kwargs["last_message_text"] == "Sunny and 72F."
        assert kwargs["last_message_at"] == "2026-01-03T00:00:00+00:00"
        assert kwargs["message_count"] == 2
        assert kwargs["ttl"] == EXPECTED_TTL

        assert response == SUCCESSFUL_RESPONSE

    @patch(f"{MODULE}.time.time", return_value=MOCK_TIME)
    async def test_last_message_determined_by_timestamp_not_list_order(self, _mock_time):
        """Ensure the latest message by created_at is chosen, not list position."""
        client = _make_client()
        client.put_messages_transaction.return_value = SUCCESSFUL_RESPONSE
        service = ConversationsService(client)

        later_message = Message(
            **{
                **MESSAGE_INPUT,
                "message_id": "01JYYYYYYYYYYYYYYYYYYYYYYYYY",
                "created_at": "2026-01-03T00:00:00+00:00",
                "content": "later content",
            }
        )
        earlier_message = Message(
            **{**MESSAGE_INPUT, "created_at": "2026-01-01T00:00:00+00:00", "content": "earlier"}
        )
        # Pass later_message first — service must still pick it by timestamp.
        await service.put_messages(USER_ID, [later_message, earlier_message])

        kwargs = client.put_messages_transaction.call_args.kwargs
        assert kwargs["last_message_text"] == "later content"
        assert kwargs["last_message_at"] == "2026-01-03T00:00:00+00:00"

    @patch(f"{MODULE}.time.time", return_value=MOCK_TIME)
    async def test_translates_transaction_canceled_to_not_found(self, _mock_time):
        client = _make_client()
        client.put_messages_transaction.side_effect = _transaction_canceled_error(
            conditional_check_failed=True
        )
        service = ConversationsService(client)

        with pytest.raises(ConversationNotFoundError) as exc_info:
            await service.put_messages(USER_ID, [Message(**MESSAGE_INPUT)])
        assert exc_info.value.user_id == USER_ID
        assert exc_info.value.conversation_id == CONVERSATION_ID

    @patch(f"{MODULE}.time.time", return_value=MOCK_TIME)
    async def test_reraises_transaction_canceled_without_condition_check(self, _mock_time):
        client = _make_client()
        client.put_messages_transaction.side_effect = _transaction_canceled_error(
            conditional_check_failed=False
        )
        service = ConversationsService(client)

        with pytest.raises(ClientError) as exc_info:
            await service.put_messages(USER_ID, [Message(**MESSAGE_INPUT)])
        assert exc_info.value.response["Error"]["Code"] == "TransactionCanceledException"
