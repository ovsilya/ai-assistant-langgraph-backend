import logging
from unittest.mock import AsyncMock, MagicMock, patch

# NOTE: AsyncMock is used for DynamoDB table operations (.put_item, .get_item,
# .query, .update_item, etc.) and for resource.Table(), which is async in aioboto3.
import pytest
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ai_assistant.clients.conversations_dynamodb import ConversationsDynamoDB
from ai_assistant.constants import (
    DELETION_JOB_STATUS_INDEX,
    QUERY_PAGE_MAX,
    QUERY_PAGE_WARNING_THRESHOLD,
)
from ai_assistant.exceptions import DeletionLeaseLostError
from ai_assistant.models import DeletionJobStatus
from config import (
    DYNAMODB_CONVERSATIONS_TABLE_NAME,
    DYNAMODB_DELETION_JOBS_TABLE_NAME,
    DYNAMODB_MESSAGES_TABLE_NAME,
)
from tests.constants import (
    CONVERSATION_ID,
    CONVERSATION_ITEM,
    EXPECTED_TTL,
    MESSAGE_ITEM,
    SUCCESSFUL_RESPONSE,
    USER_ID,
    _client_error,
    _transaction_canceled_error,
)

MODULE = "ai_assistant.clients.conversations_dynamodb"


def _table_not_found_error() -> ClientError:
    return _client_error("ResourceNotFoundException", "DescribeTable")


def _assert_query_key(mock_table, attribute: str, value: str) -> None:
    call_kwargs = mock_table.query.call_args.kwargs
    assert (
        call_kwargs["KeyConditionExpression"].get_expression()
        == Key(attribute).eq(value).get_expression()
    )


def _make_async_batch_writer(batch=None):
    """Return an async context manager mock for batch_writer()."""
    if batch is None:
        batch = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=batch)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm, batch


def _make_resource(mock_get_resource, *, tables_exist: bool = False):
    resource = MagicMock()
    conversations_table = AsyncMock()
    messages_table = AsyncMock()

    # batch_writer() must return an async CM directly (not a coroutine)
    conversations_table.batch_writer = MagicMock()
    messages_table.batch_writer = MagicMock()

    async def table_side_effect(name):
        if name == DYNAMODB_CONVERSATIONS_TABLE_NAME:
            return conversations_table
        if name == DYNAMODB_MESSAGES_TABLE_NAME:
            return messages_table
        raise ValueError(f"Unexpected table name: {name!r}")

    resource.Table = MagicMock(side_effect=table_side_effect)
    resource.meta.client = AsyncMock()

    # get_waiter is sync in aioboto3 — must not be a coroutine
    waiter = AsyncMock()
    resource.meta.client.get_waiter = MagicMock(return_value=waiter)

    if tables_exist:
        resource.meta.client.describe_table.return_value = {"Table": {}}
    else:
        resource.meta.client.describe_table.side_effect = _table_not_found_error()

    mock_get_resource.return_value = resource
    return resource, conversations_table, messages_table


# ------------------------------------------------------------------
# __init__ / ensure_tables
# ------------------------------------------------------------------


class TestConversationsDynamoDBInit:
    @patch(f"{MODULE}.get_dynamodb_resource", return_value=None)
    def test_resource_raises_when_not_initialized(self, _mock):
        db = ConversationsDynamoDB()
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = db._resource

    def test_configures_table_names(self):
        db = ConversationsDynamoDB(
            conversations_table="my_convs",
            messages_table="my_msgs",
        )

        assert db.conversations_table == "my_convs"
        assert db.messages_table == "my_msgs"

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_ensure_tables_creates_all_tables_and_enables_ttl(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        await db.ensure_tables()

        # conversations + messages + deletion_jobs
        assert resource.meta.client.create_table.await_count == 3
        assert resource.meta.client.update_time_to_live.await_count == 3

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_ensure_tables_skips_create_when_tables_already_exist(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource, tables_exist=True)

        db = ConversationsDynamoDB()
        await db.ensure_tables()

        resource.meta.client.create_table.assert_not_called()


# ------------------------------------------------------------------
# _enable_ttl
# ------------------------------------------------------------------


class TestEnableTTL:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_already_enabled_does_not_raise(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)
        resource.meta.client.update_time_to_live.side_effect = _client_error(
            "ValidationException",
            "UpdateTimeToLive",
            message="TimeToLive is already enabled",
        )

        db = ConversationsDynamoDB()
        await db._enable_ttl("convs", "ttl")  # should not raise

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_reraises_unrelated_validation_exception(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)
        resource.meta.client.update_time_to_live.side_effect = _client_error(
            "ValidationException",
            "UpdateTimeToLive",
            message="Invalid TimeToLiveSpecification",
        )

        db = ConversationsDynamoDB()
        with pytest.raises(ClientError) as exc_info:
            await db._enable_ttl("convs", "ttl")
        assert exc_info.value.response["Error"]["Code"] == "ValidationException"

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_reraises_non_validation_client_error(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)
        resource.meta.client.update_time_to_live.side_effect = _client_error(
            "AccessDeniedException",
            "UpdateTimeToLive",
        )

        db = ConversationsDynamoDB()
        with pytest.raises(ClientError) as exc_info:
            await db._enable_ttl("convs", "ttl")
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


# ------------------------------------------------------------------
# _query_all
# ------------------------------------------------------------------


class TestQueryAll:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_paginates_through_all_pages(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        page_two_item = {**CONVERSATION_ITEM, "conversation_id": "conv_page2"}
        conversations_table.query.side_effect = [
            {
                "Items": [CONVERSATION_ITEM],
                "LastEvaluatedKey": {
                    "user_id": USER_ID,
                    "conversation_id": CONVERSATION_ID,
                },
            },
            {"Items": [page_two_item]},
        ]

        db = ConversationsDynamoDB()

        items = await db._query_all(
            conversations_table,
            KeyConditionExpression=Key("user_id").eq(USER_ID),
        )

        assert len(items) == 2
        assert conversations_table.query.await_count == 2
        second_call_kwargs = conversations_table.query.call_args_list[1].kwargs
        assert second_call_kwargs["ExclusiveStartKey"] == {
            "user_id": USER_ID,
            "conversation_id": CONVERSATION_ID,
        }

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_returns_partial_results_when_page_limit_exceeded(
        self,
        mock_get_resource,
        caplog,
    ):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        stuck_key = {"user_id": USER_ID, "conversation_id": CONVERSATION_ID}
        conversations_table.query.return_value = {
            "Items": [CONVERSATION_ITEM],
            "LastEvaluatedKey": stuck_key,
        }

        db = ConversationsDynamoDB()

        with caplog.at_level(logging.ERROR):
            items = await db._query_all(
                conversations_table,
                KeyConditionExpression=Key("user_id").eq(USER_ID),
            )

        assert len(items) == QUERY_PAGE_MAX
        assert conversations_table.query.await_count == QUERY_PAGE_MAX
        assert any(
            f"{QUERY_PAGE_MAX} pages" in record.message and "partial results" in record.message
            for record in caplog.records
        )

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_raises_when_page_limit_exceeded_without_truncation(
        self,
        mock_get_resource,
        caplog,
    ):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        stuck_key = {"user_id": USER_ID, "conversation_id": CONVERSATION_ID}
        conversations_table.query.return_value = {
            "Items": [CONVERSATION_ITEM],
            "LastEvaluatedKey": stuck_key,
        }

        db = ConversationsDynamoDB()
        collected: list[list[dict[str, str]]] = []

        with (
            caplog.at_level(logging.WARNING),
            pytest.raises(RuntimeError, match=f"{QUERY_PAGE_MAX} pages"),
        ):
            async for page_items in db._iter_query_pages(
                conversations_table,
                KeyConditionExpression=Key("user_id").eq(USER_ID),
            ):
                collected.append(page_items)

        assert len(collected) == QUERY_PAGE_MAX
        assert any(
            f"{QUERY_PAGE_WARNING_THRESHOLD} pages" in record.message for record in caplog.records
        )


# ------------------------------------------------------------------
# put_conversation
# ------------------------------------------------------------------


class TestPutConversation:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_stores_item_verbatim(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        conversations_table.put_item.return_value = SUCCESSFUL_RESPONSE

        db = ConversationsDynamoDB()
        item = {**CONVERSATION_ITEM}  # pre-built dict including TTL

        response = await db.put_conversation(item)

        conversations_table.put_item.assert_awaited_once_with(
            Item=item,
            ConditionExpression="attribute_not_exists(conversation_id)",
        )
        assert response == SUCCESSFUL_RESPONSE

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_propagates_client_error_without_translation(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        conversations_table.put_item.side_effect = _client_error(
            "ConditionalCheckFailedException", "PutItem"
        )

        db = ConversationsDynamoDB()

        with pytest.raises(ClientError) as exc_info:
            await db.put_conversation(CONVERSATION_ITEM)
        assert exc_info.value.response["Error"]["Code"] == "ConditionalCheckFailedException"


# ------------------------------------------------------------------
# get_conversation_by_conversation_id
# ------------------------------------------------------------------


class TestGetConversationByConversationId:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_returns_raw_dict(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        conversations_table.get_item.return_value = {"Item": CONVERSATION_ITEM}

        db = ConversationsDynamoDB()

        result = await db.get_conversation_by_conversation_id(USER_ID, CONVERSATION_ID)

        conversations_table.get_item.assert_awaited_once_with(
            Key={"user_id": USER_ID, "conversation_id": CONVERSATION_ID}
        )
        assert result == CONVERSATION_ITEM

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_returns_none_when_missing(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        conversations_table.get_item.return_value = {}

        db = ConversationsDynamoDB()

        result = await db.get_conversation_by_conversation_id(USER_ID, CONVERSATION_ID)

        assert result is None


# ------------------------------------------------------------------
# get_conversations
# ------------------------------------------------------------------


class TestGetConversations:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_returns_raw_dicts(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        conversations_table.query.return_value = {"Items": [CONVERSATION_ITEM]}

        db = ConversationsDynamoDB()

        results = await db.get_conversations(USER_ID)

        _assert_query_key(conversations_table, "user_id", USER_ID)
        assert results == [CONVERSATION_ITEM]


# ------------------------------------------------------------------
# get_all_conversation_ids
# ------------------------------------------------------------------


class TestGetAllConversationIds:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_returns_id_set_projecting_keys_only(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        conversations_table.query.return_value = {
            "Items": [
                {"conversation_id": CONVERSATION_ID},
                {"conversation_id": "conv_two"},
            ]
        }

        db = ConversationsDynamoDB()
        ids = await db.get_all_conversation_ids(USER_ID)

        assert ids == {CONVERSATION_ID, "conv_two"}
        _assert_query_key(conversations_table, "user_id", USER_ID)
        assert conversations_table.query.call_args.kwargs["ProjectionExpression"] == (
            "conversation_id"
        )

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_raises_rather_than_truncating_past_page_limit(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        conversations_table.query.return_value = {
            "Items": [{"conversation_id": CONVERSATION_ID}],
            "LastEvaluatedKey": {"user_id": USER_ID, "conversation_id": CONVERSATION_ID},
        }

        db = ConversationsDynamoDB()
        with pytest.raises(RuntimeError, match=f"{QUERY_PAGE_MAX} pages"):
            await db.get_all_conversation_ids(USER_ID)


# ------------------------------------------------------------------
# update_conversation
# ------------------------------------------------------------------


class TestUpdateConversation:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_calls_update_item_with_provided_ttl(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        conversations_table.update_item.return_value = SUCCESSFUL_RESPONSE

        db = ConversationsDynamoDB()

        response = await db.update_conversation(
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            last_message_at="2026-01-02T00:00:00+00:00",
            last_message_text="Hello",
            message_count_delta=2,
            ttl=EXPECTED_TTL,
        )

        conversations_table.update_item.assert_awaited_once_with(
            Key={"user_id": USER_ID, "conversation_id": CONVERSATION_ID},
            UpdateExpression=(
                "SET last_message_at=:last_message_at, "
                "last_message_text=:last_message_text, "
                "#ttl=:ttl ADD message_count :message_count"
            ),
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":last_message_at": "2026-01-02T00:00:00+00:00",
                ":last_message_text": "Hello",
                ":ttl": EXPECTED_TTL,
                ":message_count": 2,
            },
            ConditionExpression="attribute_exists(conversation_id)",
            ReturnValues="UPDATED_NEW",
        )
        assert response == SUCCESSFUL_RESPONSE

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_propagates_client_error_without_translation(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        conversations_table.update_item.side_effect = _client_error(
            "ConditionalCheckFailedException", "UpdateItem"
        )

        db = ConversationsDynamoDB()

        with pytest.raises(ClientError) as exc_info:
            await db.update_conversation(
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                last_message_at="2026-01-02T00:00:00+00:00",
                last_message_text="Hello",
                message_count_delta=1,
                ttl=EXPECTED_TTL,
            )
        assert exc_info.value.response["Error"]["Code"] == "ConditionalCheckFailedException"


# ------------------------------------------------------------------
# transact_write_items
# ------------------------------------------------------------------


class TestTransactWriteItems:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_delegates_to_resource_client(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)
        resource.meta.client.transact_write_items.return_value = SUCCESSFUL_RESPONSE

        transact_items = [
            {"Put": {"TableName": "messages", "Item": {"message_id": "msg_1"}}},
            {"Update": {"TableName": "conversations", "Key": {"conversation_id": "conv_1"}}},
        ]

        db = ConversationsDynamoDB()
        response = await db.transact_write_items(transact_items)

        resource.meta.client.transact_write_items.assert_awaited_once_with(
            TransactItems=transact_items
        )
        assert response == SUCCESSFUL_RESPONSE

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_propagates_client_error(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)
        resource.meta.client.transact_write_items.side_effect = _transaction_canceled_error(
            conditional_check_failed=True
        )

        db = ConversationsDynamoDB()

        with pytest.raises(ClientError) as exc_info:
            await db.transact_write_items([])
        assert exc_info.value.response["Error"]["Code"] == "TransactionCanceledException"


# ------------------------------------------------------------------
# put_messages_transaction
# ------------------------------------------------------------------


class TestPutMessagesTransaction:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_builds_transact_items_and_delegates(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)
        resource.meta.client.transact_write_items.return_value = SUCCESSFUL_RESPONSE

        db = ConversationsDynamoDB()
        response = await db.put_messages_transaction(
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            message_items=[
                {"message_id": "msg_1", "ttl": EXPECTED_TTL},
                {"message_id": "msg_2", "ttl": EXPECTED_TTL},
            ],
            last_message_at="2026-01-03T00:00:00+00:00",
            last_message_text="latest",
            message_count=2,
            ttl=EXPECTED_TTL,
        )

        transact_items = resource.meta.client.transact_write_items.call_args.kwargs["TransactItems"]
        assert len(transact_items) == 3

        # One Put per message, targeting the messages table.
        assert transact_items[0]["Put"] == {
            "TableName": DYNAMODB_MESSAGES_TABLE_NAME,
            "Item": {"message_id": "msg_1", "ttl": EXPECTED_TTL},
        }
        assert transact_items[1]["Put"]["Item"]["message_id"] == "msg_2"

        # Conversation Update is appended last.
        update = transact_items[2]["Update"]
        assert update["TableName"] == DYNAMODB_CONVERSATIONS_TABLE_NAME
        assert update["Key"] == {"user_id": USER_ID, "conversation_id": CONVERSATION_ID}
        assert update["ConditionExpression"] == "attribute_exists(conversation_id)"
        update_values = update["ExpressionAttributeValues"]
        assert update_values[":last_message_text"] == "latest"
        assert update_values[":last_message_at"] == "2026-01-03T00:00:00+00:00"
        assert update_values[":message_count"] == 2
        assert update_values[":ttl"] == EXPECTED_TTL

        assert response == SUCCESSFUL_RESPONSE

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_propagates_client_error(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)
        resource.meta.client.transact_write_items.side_effect = _transaction_canceled_error(
            conditional_check_failed=True
        )

        db = ConversationsDynamoDB()

        with pytest.raises(ClientError) as exc_info:
            await db.put_messages_transaction(
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                message_items=[{"message_id": "msg_1", "ttl": EXPECTED_TTL}],
                last_message_at="2026-01-03T00:00:00+00:00",
                last_message_text="latest",
                message_count=1,
                ttl=EXPECTED_TTL,
            )
        assert exc_info.value.response["Error"]["Code"] == "TransactionCanceledException"


# ------------------------------------------------------------------
# get_messages_by_conversation
# ------------------------------------------------------------------


class TestGetMessagesByConversation:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_returns_raw_dicts(self, mock_get_resource):
        _, _, messages_table = _make_resource(mock_get_resource)
        messages_table.query.return_value = {"Items": [MESSAGE_ITEM]}

        db = ConversationsDynamoDB()

        results = await db.get_messages_by_conversation(CONVERSATION_ID)

        _assert_query_key(messages_table, "conversation_id", CONVERSATION_ID)
        assert results == [MESSAGE_ITEM]

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_defaults_to_newest_first(self, mock_get_resource):
        _, _, messages_table = _make_resource(mock_get_resource)
        messages_table.query.return_value = {"Items": [MESSAGE_ITEM]}

        db = ConversationsDynamoDB()
        await db.get_messages_by_conversation(CONVERSATION_ID)

        call_kwargs = messages_table.query.call_args.kwargs
        assert call_kwargs["ScanIndexForward"] is False

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_respects_scan_index_forward(self, mock_get_resource):
        _, _, messages_table = _make_resource(mock_get_resource)
        messages_table.query.return_value = {"Items": [MESSAGE_ITEM]}

        db = ConversationsDynamoDB()
        await db.get_messages_by_conversation(CONVERSATION_ID, scan_index_forward=True)

        call_kwargs = messages_table.query.call_args.kwargs
        assert call_kwargs["ScanIndexForward"] is True


# ------------------------------------------------------------------
# delete_messages_by_conversation
# ------------------------------------------------------------------


class TestDeleteMessagesByConversation:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_deletes_all_and_paginates(self, mock_get_resource):
        _, _, messages_table = _make_resource(mock_get_resource)
        page_two_message = {**MESSAGE_ITEM, "message_id": "01JYYYYYYYYYYYYYYYYYYYYYYYYY"}
        messages_table.query.side_effect = [
            {
                "Items": [MESSAGE_ITEM],
                "LastEvaluatedKey": {
                    "conversation_id": CONVERSATION_ID,
                    "message_id": MESSAGE_ITEM["message_id"],
                },
            },
            {"Items": [page_two_message]},
        ]
        cm, batch = _make_async_batch_writer()
        messages_table.batch_writer.return_value = cm

        db = ConversationsDynamoDB()

        result = await db.delete_messages_by_conversation(CONVERSATION_ID)

        assert result == 2
        assert messages_table.query.await_count == 2
        assert batch.delete_item.await_count == 2
        batch.delete_item.assert_any_call(
            Key={"conversation_id": CONVERSATION_ID, "message_id": MESSAGE_ITEM["message_id"]}
        )
        batch.delete_item.assert_any_call(
            Key={"conversation_id": CONVERSATION_ID, "message_id": page_two_message["message_id"]}
        )

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_returns_zero_when_empty(self, mock_get_resource):
        _, _, messages_table = _make_resource(mock_get_resource)
        messages_table.query.return_value = {"Items": []}

        db = ConversationsDynamoDB()

        result = await db.delete_messages_by_conversation(CONVERSATION_ID)

        assert result == 0
        messages_table.batch_writer.assert_not_called()


# ------------------------------------------------------------------
# check_table
# ------------------------------------------------------------------


class TestCheckTable:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_describes_named_table(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource, tables_exist=True)

        db = ConversationsDynamoDB()
        await db.check_table("some-table")

        resource.meta.client.describe_table.assert_awaited_once_with(TableName="some-table")


# ------------------------------------------------------------------
# initialize_conversations_table / initialize_messages_table
# ------------------------------------------------------------------


class TestInitializeConversationsTable:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_creates_table_and_enables_ttl(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        await db.initialize_conversations_table()

        call_kwargs = resource.meta.client.create_table.call_args.kwargs
        assert call_kwargs["TableName"] == DYNAMODB_CONVERSATIONS_TABLE_NAME
        assert [k["AttributeName"] for k in call_kwargs["KeySchema"]] == [
            "user_id",
            "conversation_id",
        ]
        resource.meta.client.update_time_to_live.assert_awaited_once_with(
            TableName=DYNAMODB_CONVERSATIONS_TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )

    @patch(f"{MODULE}.wait_for_table_active")
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_waits_for_active_before_ttl(self, mock_get_resource, mock_wait):
        resource, _, _ = _make_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        await db.initialize_conversations_table()

        mock_wait.assert_awaited_once_with(
            resource.meta.client,
            DYNAMODB_CONVERSATIONS_TABLE_NAME,
        )
        resource.meta.client.update_time_to_live.assert_awaited_once()


class TestInitializeMessagesTable:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_creates_table_and_enables_ttl(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        await db.initialize_messages_table()

        call_kwargs = resource.meta.client.create_table.call_args.kwargs
        assert call_kwargs["TableName"] == DYNAMODB_MESSAGES_TABLE_NAME
        assert [k["AttributeName"] for k in call_kwargs["KeySchema"]] == [
            "conversation_id",
            "message_id",
        ]
        resource.meta.client.update_time_to_live.assert_awaited_once_with(
            TableName=DYNAMODB_MESSAGES_TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )


# ------------------------------------------------------------------
# Deletion jobs
# ------------------------------------------------------------------


def _make_jobs_resource(mock_get_resource):
    """A resource whose Table() always returns a single deletion-jobs mock."""
    resource = MagicMock()
    jobs_table = AsyncMock()
    resource.Table = AsyncMock(return_value=jobs_table)
    resource.meta.client = AsyncMock()
    mock_get_resource.return_value = resource
    return resource, jobs_table


class TestDeletionJobs:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_put_deletion_job_is_conditional(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)
        jobs_table.put_item.return_value = SUCCESSFUL_RESPONSE

        db = ConversationsDynamoDB()
        response = await db.put_deletion_job({"job_id": "j1", "user_id": USER_ID})

        jobs_table.put_item.assert_awaited_once_with(
            Item={"job_id": "j1", "user_id": USER_ID},
            ConditionExpression="attribute_not_exists(job_id)",
        )
        assert response == SUCCESSFUL_RESPONSE

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_get_deletion_job_returns_item_or_none(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)
        jobs_table.get_item.return_value = {"Item": {"job_id": "j1"}}

        db = ConversationsDynamoDB()
        assert await db.get_deletion_job("j1") == {"job_id": "j1"}

        jobs_table.get_item.return_value = {}
        assert await db.get_deletion_job("j1") is None

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_get_resumable_jobs_queries_both_statuses_via_gsi(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)
        jobs_table.query.side_effect = [
            {"Items": [{"job_id": "pending_job"}]},
            {"Items": [{"job_id": "in_progress_job"}]},
        ]

        db = ConversationsDynamoDB()
        items = await db.get_resumable_jobs(limit=25)

        assert [i["job_id"] for i in items] == ["pending_job", "in_progress_job"]
        assert jobs_table.query.await_count == 2
        first_call = jobs_table.query.call_args_list[0].kwargs
        assert first_call["IndexName"] == DELETION_JOB_STATUS_INDEX
        assert first_call["Limit"] == 25
        assert (
            first_call["KeyConditionExpression"].get_expression()
            == Key("status").eq(DeletionJobStatus.PENDING.value).get_expression()
        )

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_claim_deletion_job_success(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        claimed = await db.claim_deletion_job("j1", owner="w1", lease_expiry=200, now_epoch=100)

        assert claimed is True
        call = jobs_table.update_item.call_args.kwargs
        assert "attempts" not in call["UpdateExpression"]
        assert "lease_expiry < :now_s" in call["ConditionExpression"]
        assert call["ExpressionAttributeValues"][":owner"] == "w1"
        assert call["ExpressionAttributeValues"][":now_s"] == 100

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_claim_deletion_job_counts_attempt_when_reclaiming(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        claimed = await db.claim_deletion_job(
            "j1", owner="w1", lease_expiry=200, now_epoch=100, count_as_attempt=True
        )

        assert claimed is True
        call = jobs_table.update_item.call_args.kwargs
        assert "ADD attempts :one" in call["UpdateExpression"]
        assert call["ExpressionAttributeValues"][":one"] == 1

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_claim_deletion_job_returns_false_when_lease_held(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)
        jobs_table.update_item.side_effect = _client_error(
            "ConditionalCheckFailedException", "UpdateItem"
        )

        db = ConversationsDynamoDB()
        assert await db.claim_deletion_job("j1", "w1", 200, 100) is False

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_claim_deletion_job_reraises_other_errors(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)
        jobs_table.update_item.side_effect = _client_error("AccessDeniedException", "UpdateItem")

        db = ConversationsDynamoDB()
        with pytest.raises(ClientError):
            await db.claim_deletion_job("j1", "w1", 200, 100)

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_set_in_progress_sets_status(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        await db.set_deletion_job_in_progress("j1", conversations_deleted=3, owner="w1")

        call = jobs_table.update_item.call_args.kwargs
        assert call["ExpressionAttributeNames"] == {"#status": "status"}
        assert call["ExpressionAttributeValues"][":s"] == DeletionJobStatus.IN_PROGRESS.value
        assert call["ExpressionAttributeValues"][":c"] == 3
        assert call["ConditionExpression"] == "lease_owner = :owner"
        assert call["ExpressionAttributeValues"][":owner"] == "w1"

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_checkpoint_removes_id_and_adds_count(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        await db.checkpoint_conversation_deleted(
            "j1", "conv_1", messages_deleted_delta=4, owner="w1"
        )

        call = jobs_table.update_item.call_args.kwargs
        assert "DELETE pending_conversation_ids :ids" in call["UpdateExpression"]
        assert "ADD messages_deleted :m" in call["UpdateExpression"]
        assert call["ExpressionAttributeValues"][":ids"] == {"conv_1"}
        assert call["ExpressionAttributeValues"][":m"] == 4
        assert call["ConditionExpression"] == "lease_owner = :owner"
        assert call["ExpressionAttributeValues"][":owner"] == "w1"

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_checkpoint_raises_lease_lost_on_condition_failure(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)
        jobs_table.update_item.side_effect = _client_error(
            "ConditionalCheckFailedException", "UpdateItem"
        )

        db = ConversationsDynamoDB()
        with pytest.raises(DeletionLeaseLostError):
            await db.checkpoint_conversation_deleted("j1", "conv_1", 4, owner="w1")

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_finish_releases_lease_sets_status_and_stamps_ttl(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        await db.finish_deletion_job("j1", DeletionJobStatus.COMPLETE, owner="w1")

        call = jobs_table.update_item.call_args.kwargs
        assert "REMOVE lease_owner, lease_expiry" in call["UpdateExpression"]
        assert call["ExpressionAttributeNames"] == {"#status": "status", "#ttl": "ttl"}
        assert call["ExpressionAttributeValues"][":s"] == DeletionJobStatus.COMPLETE.value
        assert call["ExpressionAttributeValues"][":ttl"] > 0
        assert call["ConditionExpression"] == "lease_owner = :owner"
        assert call["ExpressionAttributeValues"][":owner"] == "w1"

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_finish_raises_lease_lost_on_condition_failure(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)
        jobs_table.update_item.side_effect = _client_error(
            "ConditionalCheckFailedException", "UpdateItem"
        )

        db = ConversationsDynamoDB()
        with pytest.raises(DeletionLeaseLostError):
            await db.finish_deletion_job("j1", DeletionJobStatus.COMPLETE, owner="w1")

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_record_error_truncates_bumps_attempts_releases_lease(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        await db.record_deletion_job_error("j1", "x" * 5000, owner="w1")

        call = jobs_table.update_item.call_args.kwargs
        assert len(call["ExpressionAttributeValues"][":e"]) == 1000
        assert "REMOVE lease_owner, lease_expiry" in call["UpdateExpression"]
        assert "ADD attempts :one" in call["UpdateExpression"]
        assert call["ConditionExpression"] == "lease_owner = :owner"
        assert call["ExpressionAttributeValues"][":owner"] == "w1"

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_record_error_is_noop_when_lease_lost(self, mock_get_resource):
        _, jobs_table = _make_jobs_resource(mock_get_resource)
        jobs_table.update_item.side_effect = _client_error(
            "ConditionalCheckFailedException", "UpdateItem"
        )

        db = ConversationsDynamoDB()
        await db.record_deletion_job_error("j1", "boom", owner="w1")


class TestDeleteConversationsByIds:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_empty_returns_zero_without_batch(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        assert await db.delete_conversations_by_ids(USER_ID, []) == 0
        conversations_table.batch_writer.assert_not_called()

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_deletes_each_key(self, mock_get_resource):
        _, conversations_table, _ = _make_resource(mock_get_resource)
        cm, batch = _make_async_batch_writer()
        conversations_table.batch_writer.return_value = cm

        db = ConversationsDynamoDB()
        result = await db.delete_conversations_by_ids(USER_ID, ["c1", "c2"])

        assert result == 2
        assert batch.delete_item.await_count == 2
        batch.delete_item.assert_any_call(Key={"user_id": USER_ID, "conversation_id": "c1"})
        batch.delete_item.assert_any_call(Key={"user_id": USER_ID, "conversation_id": "c2"})


class TestInitializeDeletionJobsTable:
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_creates_table_with_status_gsi_and_ttl(self, mock_get_resource):
        resource, _, _ = _make_resource(mock_get_resource)

        db = ConversationsDynamoDB()
        await db.initialize_deletion_jobs_table()

        call_kwargs = resource.meta.client.create_table.call_args.kwargs
        assert call_kwargs["TableName"] == DYNAMODB_DELETION_JOBS_TABLE_NAME
        assert call_kwargs["KeySchema"] == [{"AttributeName": "job_id", "KeyType": "HASH"}]
        gsi = call_kwargs["GlobalSecondaryIndexes"][0]
        assert gsi["IndexName"] == DELETION_JOB_STATUS_INDEX
        assert [k["AttributeName"] for k in gsi["KeySchema"]] == ["status", "created_at"]
        resource.meta.client.update_time_to_live.assert_awaited_once_with(
            TableName=DYNAMODB_DELETION_JOBS_TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )
