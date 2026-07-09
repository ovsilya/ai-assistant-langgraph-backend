import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from ai_assistant.agent.graph import graph
from ai_assistant.api.chat import _build_initial_state, _to_response
from ai_assistant.api.schemas import ChatRequest, ChatResponse
from application import server as app
from config import SITE_ID_DEFAULT


class TestChatRequest:
    def test_minimal_valid_request(self):
        req = ChatRequest(user_id="u1", message="Hello")
        assert req.conversation_id is None

    def test_requires_user_id_and_message(self):
        with pytest.raises(ValidationError):
            ChatRequest(user_id="u1")


class TestChatResponse:
    def test_response_shape(self):
        resp = ChatResponse(
            response="Hi there",
            conversation_id="conv-1",
            title="Hello",
            model_used="claude-sonnet-4-6",
            recommendations={"related": [{"id": "a1", "title": "T", "url": "https://x"}]},
            topics=["cars"],
            follow_up_suggestions=["Tell me more"],
            intent="content_question",
        )
        data = resp.model_dump()
        assert data["response"] == "Hi there"
        assert data["recommendations"]["related"][0]["id"] == "a1"


class TestRouteHelpers:
    def test_build_initial_state(self):
        req = ChatRequest(
            user_id="u1",
            message="What cars?",
            url="https://www.meridian.example.com/lifestyle/cars",
        )
        state = _build_initial_state(req, "brand_alpha_us")
        assert state["user_id"] == "u1"
        assert state["site_id"] == "brand_alpha_us"
        assert "messages" not in state
        assert isinstance(state["current_message"], HumanMessage)
        assert state["current_message"].content == "What cars?"

    def test_to_response_maps_graph_state(self):
        state = {
            "response": "Try the Lucid Air review.",
            "conversation_id": "abc-123",
            "title": "Electric SUVs",
            "model_used": "claude-sonnet-4-6",
            "guardrail_triggered": None,
            "related_articles": [{"id": "x", "title": "Lucid", "url": "https://www.meridian.example.com/lucid"}],
            "query_index_articles": [
                {"id": "y", "title": "Hotels", "url": "https://www.meridian.example.com/hotels"}
            ],
            "topics": ["EVs"],
            "follow_up_suggestions": ["Which Lucid trim?"],
            "intent": "content_question",
        }
        resp = _to_response(state)
        assert resp.response.startswith("Try the Lucid")
        assert resp.conversation_id == "abc-123"
        assert len(resp.recommendations.related) == 1
        assert len(resp.recommendations.query_index) == 1
        assert resp.intent == "content_question"


class TestChatApiValidation:
    def test_post_chat_invalid_body_returns_422(self):
        client = TestClient(app)
        resp = client.post("/v1/assistant/chat", json={"message": "missing user_id"})
        assert resp.status_code == 422


class TestEmptyMessageShortCircuit:
    def test_empty_message_never_invokes_graph(self, monkeypatch):
        async def _fail_if_called(*args, **kwargs):
            raise AssertionError("graph.ainvoke should not run for an empty message")

        monkeypatch.setattr(graph, "ainvoke", _fail_if_called)

        client = TestClient(app)
        resp = client.post(
            "/v1/assistant/chat",
            json={"user_id": "u1", "message": "   "},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["guardrail_triggered"] == "empty_input"
        assert data["model_used"] == "fallback"
        assert data["conversation_id"]
        assert data["response"].strip()


class TestSiteIdRouting:
    """site_id is a URL path segment (Concorde convention), not a body field."""

    def test_site_id_in_path_is_resolved_and_passed_to_graph(self, monkeypatch):
        captured = {}

        async def fake_ainvoke(state):
            captured.update(state)
            return {"response": "ok", "conversation_id": "conv-1"}

        monkeypatch.setattr(graph, "ainvoke", fake_ainvoke)

        client = TestClient(app)
        resp = client.post(
            "/v1/assistant/chat/brand_alpha",
            json={"user_id": "u1", "message": "hi"},
        )
        assert resp.status_code == 200
        assert captured["site_id"] == "brand_alpha_us"

    def test_missing_site_id_path_falls_back_to_default(self, monkeypatch):
        captured = {}

        async def fake_ainvoke(state):
            captured.update(state)
            return {"response": "ok", "conversation_id": "conv-1"}

        monkeypatch.setattr(graph, "ainvoke", fake_ainvoke)

        client = TestClient(app)
        resp = client.post(
            "/v1/assistant/chat",
            json={"user_id": "u1", "message": "hi"},
        )
        assert resp.status_code == 200
        assert captured["site_id"] == SITE_ID_DEFAULT


class TestConversationIdHeader:
    """Concorde convention: expose conversation_id as a response header too."""

    def test_new_conversation_sets_header(self, monkeypatch):
        async def fake_ainvoke(state):
            return {"response": "ok", "conversation_id": "new-conv-id"}

        monkeypatch.setattr(graph, "ainvoke", fake_ainvoke)

        client = TestClient(app)
        resp = client.post(
            "/v1/assistant/chat",
            json={"user_id": "u1", "message": "hi"},
        )
        assert resp.headers.get("conversation_id") == "new-conv-id"

    def test_followup_turn_does_not_set_header(self, monkeypatch):
        async def fake_ainvoke(state):
            return {"response": "ok", "conversation_id": "existing-conv-id"}

        monkeypatch.setattr(graph, "ainvoke", fake_ainvoke)

        client = TestClient(app)
        resp = client.post(
            "/v1/assistant/chat",
            json={"user_id": "u1", "message": "hi", "conversation_id": "existing-conv-id"},
        )
        assert "conversation_id" not in resp.headers
