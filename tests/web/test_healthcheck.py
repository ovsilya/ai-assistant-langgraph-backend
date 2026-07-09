import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from application import server
from config import (
    DYNAMODB_CONVERSATIONS_TABLE_NAME,
    DYNAMODB_MESSAGES_TABLE_NAME,
    ENVIRONMENT,
)

MODULE = "ai_assistant.api.health"


class TestHealthEndpoint:
    @pytest.fixture(autouse=True)
    def _patch_lifespan(self):
        """Suppress the FastAPI lifespan DynamoDB calls for every test."""
        with (
            patch("application.open_dynamodb_resource", new_callable=AsyncMock),
            patch("application.close_dynamodb_resource", new_callable=AsyncMock),
            patch("application.initialize_dynamodb_tables", new_callable=AsyncMock) as mock_init,
        ):
            self.mock_init = mock_init
            yield

    @pytest.mark.parametrize("path", ["/health", "/health/"])
    def test_returns_plain_ok(self, path):
        with TestClient(server) as client:
            response = client.get(path)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @patch(f"{MODULE}.get_conversations_dynamodb")
    @patch(f"{MODULE}.get_dynamodb_client")
    def test_does_not_probe_dynamodb_on_liveness_request(
        self,
        mock_get_dynamodb,
        mock_get_conversations,
    ):
        with TestClient(server) as client:
            client.get("/health")

        mock_get_dynamodb.assert_not_called()
        mock_get_conversations.assert_not_called()

    @patch(f"{MODULE}.get_conversations_dynamodb")
    @patch(f"{MODULE}.get_dynamodb_client")
    def test_dynamodb_probes_tables_and_returns_client_table_names(
        self, mock_get_dynamodb, mock_get_conversations
    ):
        dynamodb_client = MagicMock()
        dynamodb_client.status_table = "configured-status-table"
        dynamodb_client.check_status_table = AsyncMock()
        conversations_client = MagicMock()
        conversations_client.conversations_table = "custom-conversations-table"
        conversations_client.messages_table = "custom-messages-table"
        conversations_client.check_table = AsyncMock()
        mock_get_dynamodb.return_value = dynamodb_client
        mock_get_conversations.return_value = conversations_client

        with TestClient(server) as client:
            response = client.get("/health/dynamodb")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "env": ENVIRONMENT,
            "results": {
                "status_table": {"status": "ok", "table": "configured-status-table"},
                "conversations_table": {
                    "status": "ok",
                    "table": "custom-conversations-table",
                },
                "messages_table": {"status": "ok", "table": "custom-messages-table"},
            },
        }
        dynamodb_client.check_status_table.assert_called_once()
        conversations_client.check_table.assert_any_call("custom-conversations-table")
        conversations_client.check_table.assert_any_call("custom-messages-table")
        assert conversations_client.check_table.call_count == 2

    @pytest.mark.parametrize(
        "failing_table,expected_results",
        [
            pytest.param(
                "status_table",
                {
                    "status_table": {"status": "failed", "table": "configured-status-table"},
                    "conversations_table": {
                        "status": "ok",
                        "table": DYNAMODB_CONVERSATIONS_TABLE_NAME,
                    },
                    "messages_table": {"status": "ok", "table": DYNAMODB_MESSAGES_TABLE_NAME},
                },
                id="status_table_fails",
            ),
            pytest.param(
                DYNAMODB_CONVERSATIONS_TABLE_NAME,
                {
                    "status_table": {"status": "ok", "table": "configured-status-table"},
                    "conversations_table": {
                        "status": "failed",
                        "table": DYNAMODB_CONVERSATIONS_TABLE_NAME,
                    },
                    "messages_table": {"status": "ok", "table": DYNAMODB_MESSAGES_TABLE_NAME},
                },
                id="conversations_table_fails",
            ),
            pytest.param(
                DYNAMODB_MESSAGES_TABLE_NAME,
                {
                    "status_table": {"status": "ok", "table": "configured-status-table"},
                    "conversations_table": {
                        "status": "ok",
                        "table": DYNAMODB_CONVERSATIONS_TABLE_NAME,
                    },
                    "messages_table": {
                        "status": "failed",
                        "table": DYNAMODB_MESSAGES_TABLE_NAME,
                    },
                },
                id="messages_table_fails",
            ),
        ],
    )
    @patch(f"{MODULE}.get_conversations_dynamodb")
    @patch(f"{MODULE}.get_dynamodb_client")
    def test_dynamodb_returns_500_when_table_check_fails(
        self, mock_get_dynamodb, mock_get_conversations, failing_table, expected_results
    ):
        dynamodb_client = MagicMock()
        dynamodb_client.status_table = "configured-status-table"
        dynamodb_client.check_status_table = AsyncMock(
            side_effect=RuntimeError("down") if failing_table == "status_table" else None
        )

        conversations_client = MagicMock()
        conversations_client.conversations_table = DYNAMODB_CONVERSATIONS_TABLE_NAME
        conversations_client.messages_table = DYNAMODB_MESSAGES_TABLE_NAME

        def _check_table(table_name):
            if table_name == failing_table:
                raise RuntimeError(f"{table_name} down")

        conversations_client.check_table = AsyncMock(side_effect=_check_table)
        mock_get_dynamodb.return_value = dynamodb_client
        mock_get_conversations.return_value = conversations_client

        with TestClient(server) as client:
            response = client.get("/health/dynamodb")

        assert response.status_code == 500
        assert response.json() == {
            "status": "unhealthy",
            "env": ENVIRONMENT,
            "results": expected_results,
        }

    @patch(f"{MODULE}.asyncio.wait_for", side_effect=asyncio.TimeoutError)
    def test_dynamodb_returns_500_on_timeout(self, _mock_wait_for):
        with TestClient(server) as client:
            response = client.get("/health/dynamodb")

        assert response.status_code == 500
        assert response.json() == {"status": "unhealthy", "error": "health check timed out"}
