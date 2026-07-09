from unittest.mock import AsyncMock, patch

import pytest

from ai_assistant.clients.dynamodb_init import initialize_dynamodb_tables


class TestInitializeDynamodbTables:
    @patch("ai_assistant.clients.dynamodb_init.get_conversations_dynamodb")
    @patch("ai_assistant.clients.dynamodb_init.get_dynamodb_client")
    async def test_ensures_all_tables(self, mock_get_dynamodb, mock_get_conversations):
        status_client = AsyncMock()
        conversations_client = AsyncMock()
        mock_get_dynamodb.return_value = status_client
        mock_get_conversations.return_value = conversations_client

        await initialize_dynamodb_tables()

        status_client.provision_status_table.assert_awaited_once_with()
        conversations_client.ensure_tables.assert_awaited_once_with()

    @patch("ai_assistant.clients.dynamodb_init.get_conversations_dynamodb")
    @patch("ai_assistant.clients.dynamodb_init.get_dynamodb_client")
    async def test_raises_exception_group_when_both_inits_fail(
        self, mock_get_dynamodb, mock_get_conversations
    ):
        status_error = RuntimeError("status table failed")
        conversations_error = RuntimeError("conversations table failed")
        status_client = AsyncMock()
        status_client.provision_status_table.side_effect = status_error
        conversations_client = AsyncMock()
        conversations_client.ensure_tables.side_effect = conversations_error
        mock_get_dynamodb.return_value = status_client
        mock_get_conversations.return_value = conversations_client

        with pytest.raises(
            ExceptionGroup, match="DynamoDB table initialisation failed"
        ) as exc_info:
            await initialize_dynamodb_tables()

        assert exc_info.value.exceptions == (status_error, conversations_error)
        status_client.provision_status_table.assert_awaited_once_with()
        conversations_client.ensure_tables.assert_awaited_once_with()

    @patch("ai_assistant.clients.dynamodb_init.get_conversations_dynamodb")
    @patch("ai_assistant.clients.dynamodb_init.get_dynamodb_client")
    async def test_raises_exception_group_when_one_init_fails(
        self, mock_get_dynamodb, mock_get_conversations
    ):
        status_error = RuntimeError("status table failed")
        status_client = AsyncMock()
        status_client.provision_status_table.side_effect = status_error
        conversations_client = AsyncMock()
        mock_get_dynamodb.return_value = status_client
        mock_get_conversations.return_value = conversations_client

        with pytest.raises(
            ExceptionGroup, match="DynamoDB table initialisation failed"
        ) as exc_info:
            await initialize_dynamodb_tables()

        assert exc_info.value.exceptions == (status_error,)
        status_client.provision_status_table.assert_awaited_once_with()
        conversations_client.ensure_tables.assert_awaited_once_with()

    @patch("ai_assistant.clients.dynamodb_init.get_conversations_dynamodb")
    @patch("ai_assistant.clients.dynamodb_init.get_dynamodb_client")
    async def test_raises_exception_group_when_only_conversations_init_fails(
        self, mock_get_dynamodb, mock_get_conversations
    ):
        conversations_error = RuntimeError("conversations table failed")
        status_client = AsyncMock()
        conversations_client = AsyncMock()
        conversations_client.ensure_tables.side_effect = conversations_error
        mock_get_dynamodb.return_value = status_client
        mock_get_conversations.return_value = conversations_client

        with pytest.raises(
            ExceptionGroup, match="DynamoDB table initialisation failed"
        ) as exc_info:
            await initialize_dynamodb_tables()

        assert exc_info.value.exceptions == (conversations_error,)
        status_client.provision_status_table.assert_awaited_once_with()
        conversations_client.ensure_tables.assert_awaited_once_with()
