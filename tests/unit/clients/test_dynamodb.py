import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import ai_assistant.clients.dynamodb as dynamodb_module
from ai_assistant.clients.conversations_dynamodb import get_conversations_dynamodb
from ai_assistant.clients.dynamodb import (
    DynamoDB,
    close_dynamodb_resource,
    create_table_if_absent,
    get_dynamodb_client,
    get_dynamodb_resource,
    open_dynamodb_resource,
    table_exists,
)
from config import DYNAMODB_STATUS_TABLE_NAME

MODULE = "ai_assistant.clients.dynamodb"


def _table_not_found_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
        "DescribeTable",
    )


def _make_resource():
    resource = MagicMock()
    resource.meta.client = AsyncMock()
    resource.Table = AsyncMock(return_value=AsyncMock())
    return resource


class TestDynamoDB:
    def test_uses_config_status_table_name(self):
        assert DynamoDB().table_name == DYNAMODB_STATUS_TABLE_NAME

    def test_status_table_property_returns_table_name_string(self):
        assert DynamoDB(table_name="ai-assistant-status").status_table == "ai-assistant-status"

    @patch(f"{MODULE}.get_dynamodb_resource", return_value=None)
    def test_resource_raises_when_not_initialized(self, _mock):
        dynamodb = DynamoDB()
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = dynamodb._resource

    @patch(f"{MODULE}.get_dynamodb_resource")
    def test_constructor_does_not_create_status_table(self, mock_get_resource):
        # Construction must be side-effect-free: no network calls, no table creation.
        DynamoDB(table_name="ai-assistant-status")

        mock_get_resource.assert_not_called()

    @patch(f"{MODULE}.wait_for_table_active")
    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_provision_status_table_creates_status_table(self, mock_get_resource, mock_wait):
        resource = _make_resource()
        resource.meta.client.describe_table.side_effect = _table_not_found_error()
        mock_get_resource.return_value = resource

        await DynamoDB(table_name="ai-assistant-status").provision_status_table()

        resource.meta.client.describe_table.assert_awaited_once_with(
            TableName="ai-assistant-status"
        )
        resource.meta.client.create_table.assert_awaited_once()
        mock_wait.assert_awaited_once_with(resource.meta.client, "ai-assistant-status")

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_provision_status_table_skips_create_when_table_exists(self, mock_get_resource):
        resource = _make_resource()
        resource.meta.client.describe_table.return_value = {"Table": {}}
        mock_get_resource.return_value = resource

        await DynamoDB(table_name="ai-assistant-status").provision_status_table()

        resource.meta.client.describe_table.assert_awaited_once_with(
            TableName="ai-assistant-status"
        )
        resource.meta.client.create_table.assert_not_called()

    @patch(f"{MODULE}.get_dynamodb_resource")
    async def test_check_status_table_describes_table(self, mock_get_resource):
        resource = _make_resource()
        mock_get_resource.return_value = resource

        dynamodb = DynamoDB(table_name="ai-assistant-status")
        await dynamodb.check_status_table()

        resource.meta.client.describe_table.assert_awaited_once_with(
            TableName="ai-assistant-status"
        )


class TestTableExists:
    async def test_returns_true_when_describe_succeeds(self):
        client = AsyncMock()
        client.describe_table.return_value = {"Table": {}}

        assert await table_exists(client, "some-table") is True
        client.describe_table.assert_awaited_once_with(TableName="some-table")

    async def test_returns_false_when_not_found(self):
        client = AsyncMock()
        client.describe_table.side_effect = _table_not_found_error()

        assert await table_exists(client, "some-table") is False

    async def test_reraises_other_client_errors(self):
        client = AsyncMock()
        client.describe_table.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "AccessDeniedException"}},
            "DescribeTable",
        )

        with pytest.raises(ClientError) as exc_info:
            await table_exists(client, "some-table")
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


class TestCreateTableIfAbsent:
    async def test_skips_create_when_table_exists(self):
        client = AsyncMock()
        client.describe_table.return_value = {"Table": {}}

        created = await create_table_if_absent(client, "some-table", {"KeySchema": []})

        assert created is False
        client.create_table.assert_not_called()

    async def test_creates_when_absent(self):
        client = AsyncMock()
        client.describe_table.side_effect = _table_not_found_error()

        created = await create_table_if_absent(client, "some-table", {"KeySchema": []})

        assert created is True
        client.create_table.assert_awaited_once_with(TableName="some-table", KeySchema=[])

    async def test_tolerates_concurrent_creator(self):
        client = AsyncMock()
        client.describe_table.side_effect = _table_not_found_error()
        client.create_table.side_effect = ClientError(
            {"Error": {"Code": "ResourceInUseException", "Message": "ResourceInUseException"}},
            "CreateTable",
        )

        created = await create_table_if_absent(client, "some-table", {"KeySchema": []})

        assert created is True

    async def test_reraises_other_client_errors_on_create(self):
        client = AsyncMock()
        client.describe_table.side_effect = _table_not_found_error()
        client.create_table.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "AccessDeniedException"}},
            "CreateTable",
        )

        with pytest.raises(ClientError) as exc_info:
            await create_table_if_absent(client, "some-table", {"KeySchema": []})
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


@pytest.fixture(autouse=True)
def reset_dynamodb_session_globals():
    """Reset module-level session globals before each test."""
    dynamodb_module._resource = None
    dynamodb_module._resource_cm = None
    dynamodb_module._lock = asyncio.Lock()
    yield


class TestOpenCloseDynamodbResource:
    async def test_open_sets_resource(self):
        resource = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resource)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch(f"{MODULE}.aioboto3.Session") as mock_session_cls:
            mock_session_cls.return_value.resource.return_value = cm
            await open_dynamodb_resource()

        assert get_dynamodb_resource() is resource

    async def test_close_clears_resource(self):
        resource = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resource)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch(f"{MODULE}.aioboto3.Session") as mock_session_cls:
            mock_session_cls.return_value.resource.return_value = cm
            await open_dynamodb_resource()
            first_dynamodb = get_dynamodb_client()
            first_conversations = get_conversations_dynamodb()
            await close_dynamodb_resource()

        assert get_dynamodb_resource() is None
        cm.__aexit__.assert_awaited_once()
        assert get_dynamodb_client() is not first_dynamodb
        assert get_conversations_dynamodb() is not first_conversations

    async def test_close_clears_caches_even_when_aexit_raises(self):
        resource = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resource)
        cm.__aexit__ = AsyncMock(side_effect=RuntimeError("close failed"))

        with patch(f"{MODULE}.aioboto3.Session") as mock_session_cls:
            mock_session_cls.return_value.resource.return_value = cm
            await open_dynamodb_resource()
            first_dynamodb = get_dynamodb_client()
            first_conversations = get_conversations_dynamodb()

        with pytest.raises(RuntimeError, match="close failed"):
            await close_dynamodb_resource()

        assert get_dynamodb_resource() is None
        assert get_dynamodb_client() is not first_dynamodb
        assert get_conversations_dynamodb() is not first_conversations

    async def test_open_cleans_up_cm_when_aenter_raises(self):
        error = RuntimeError("connection refused")
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=error)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch(f"{MODULE}.aioboto3.Session") as mock_session_cls:
            mock_session_cls.return_value.resource.return_value = cm
            with pytest.raises(RuntimeError, match="connection refused"):
                await open_dynamodb_resource()

        # Resource must not be set — a half-open state would silently corrupt callers.
        assert get_dynamodb_resource() is None
        # The CM must have received __aexit__ so it can release any resources it
        # allocated before __aenter__ raised.
        cm.__aexit__.assert_awaited_once()
        exc_type, exc_val, _ = cm.__aexit__.call_args.args
        assert exc_type is RuntimeError
        assert exc_val is error

    async def test_close_is_safe_when_not_open(self):
        await close_dynamodb_resource()
        assert get_dynamodb_resource() is None

    async def test_open_raises_when_already_open(self):
        resource = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resource)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch(f"{MODULE}.aioboto3.Session") as mock_session_cls:
            mock_session_cls.return_value.resource.return_value = cm
            await open_dynamodb_resource()
            with pytest.raises(RuntimeError, match="already open"):
                await open_dynamodb_resource()

    async def test_concurrent_open_waits_for_first_then_raises(self):
        resource = MagicMock()
        enter_started = asyncio.Event()
        allow_enter = asyncio.Event()

        async def slow_enter():
            enter_started.set()
            await allow_enter.wait()
            return resource

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=slow_enter)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch(f"{MODULE}.aioboto3.Session") as mock_session_cls:
            mock_session_cls.return_value.resource.return_value = cm
            first = asyncio.create_task(open_dynamodb_resource())
            await enter_started.wait()
            second = asyncio.create_task(open_dynamodb_resource())
            await asyncio.sleep(0)
            allow_enter.set()
            await first
            with pytest.raises(RuntimeError, match="already open"):
                await second


class TestDynamodbClientsShareResource:
    async def test_dynamodb_clients_share_resource(self):
        resource = MagicMock()
        resource.meta.client = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=resource)
        cm.__aexit__ = AsyncMock(return_value=None)

        with patch(f"{MODULE}.aioboto3.Session") as mock_session_cls:
            mock_session_cls.return_value.resource.return_value = cm
            await open_dynamodb_resource()

        from ai_assistant.clients.conversations_dynamodb import ConversationsDynamoDB

        status_db = DynamoDB()
        conversations_db = ConversationsDynamoDB()

        assert status_db._resource is conversations_db._resource
