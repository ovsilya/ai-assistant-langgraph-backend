from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ai_assistant.models import DeletionJob, DeletionJobStatus
from application import server

MODULE = "ai_assistant.api.user_data"


class TestUserDataDeletionApi:
    @pytest.fixture(autouse=True)
    def _patch_lifespan(self):
        """Suppress the FastAPI lifespan DynamoDB calls for every test."""
        with (
            patch("application.open_dynamodb_resource", new_callable=AsyncMock),
            patch("application.close_dynamodb_resource", new_callable=AsyncMock),
            patch("application.initialize_dynamodb_tables", new_callable=AsyncMock),
        ):
            yield

    @patch(f"{MODULE}.get_conversations_service")
    def test_request_returns_202_with_job_id(self, mock_get_service):
        service = MagicMock()
        service.request_user_data_deletion = AsyncMock(return_value="job_123")
        mock_get_service.return_value = service

        with TestClient(server) as client:
            response = client.post("/users/user_abc/deletion-requests")

        assert response.status_code == 202
        assert response.json() == {"job_id": "job_123", "status": "pending"}
        service.request_user_data_deletion.assert_awaited_once_with("user_abc")

    @patch(f"{MODULE}.get_conversations_service")
    def test_get_returns_job_state(self, mock_get_service):
        service = MagicMock()
        service.get_deletion_job = AsyncMock(
            return_value=DeletionJob(
                job_id="job_123",
                user_id="user_abc",
                status=DeletionJobStatus.IN_PROGRESS,
                pending_conversation_ids={"c1", "c2"},
                conversations_deleted=3,
                messages_deleted=7,
            )
        )
        mock_get_service.return_value = service

        with TestClient(server) as client:
            response = client.get("/deletion-requests/job_123")

        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == "job_123"
        assert body["status"] == "IN_PROGRESS"
        assert body["conversations_deleted"] == 3
        assert body["messages_deleted"] == 7
        assert body["pending_conversations"] == 2

    @patch(f"{MODULE}.get_conversations_service")
    def test_get_returns_404_when_missing(self, mock_get_service):
        service = MagicMock()
        service.get_deletion_job = AsyncMock(return_value=None)
        mock_get_service.return_value = service

        with TestClient(server) as client:
            response = client.get("/deletion-requests/missing")

        assert response.status_code == 404
        assert response.json()["error"] == "not_found"
