"""HTTP integration tests for POST /v1/assistant/chat."""

import pytest
from fastapi.testclient import TestClient

from application import server as app
from tests.conftest import MOCK_QUERY_INDEX, MOCK_RELATED, assert_chat_response


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.integration
class TestChatApi:
    def test_post_chat_content_question(
        self, client, require_ai_gateway, mock_concorde, brand_alpha_chat_payload
    ):
        resp = client.post("/v1/assistant/chat/brand_alpha_us", json=brand_alpha_chat_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert_chat_response(data, expected_intent="content_question")
        assert data["model_used"]
        assert len(data["recommendations"]["related"]) >= 1
        assert len(data["recommendations"]["query_index"]) >= 1
        assert data["recommendations"]["related"][0]["id"] == MOCK_RELATED[0]["id"]
        assert data["recommendations"]["query_index"][0]["id"] == MOCK_QUERY_INDEX[0]["id"]

    def test_post_chat_small_talk(self, client, require_ai_gateway, mock_concorde):
        resp = client.post(
            "/v1/assistant/chat/brand_alpha_us",
            json={
                "user_id": "test_user_2",
                "message": "Hi there!",
                "url": "https://www.meridian.example.com/",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert_chat_response(data)
        assert data["intent"] in ("small_talk", "content_question")

    def test_post_chat_blocked(self, client, require_ai_gateway, mock_concorde):
        resp = client.post(
            "/v1/assistant/chat/brand_alpha_us",
            json={
                "user_id": "test_user_3",
                "message": (
                    "What prescription drug should I take for chest pain? Give medical diagnosis."
                ),
                "url": "https://www.meridian.example.com/",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert_chat_response(data)
        assert data.get("guardrail_triggered") == "input_topic_block"
