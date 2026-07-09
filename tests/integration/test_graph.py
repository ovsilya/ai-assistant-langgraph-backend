"""LangGraph end-to-end tests — real ai-gateway LLM, mocked Concorde."""

import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from ai_assistant.agent.graph import graph
from config import CONCORDE_TEST_CONTENT_ID
from tests.conftest import MOCK_QUERY_INDEX, MOCK_RELATED, assert_chat_response

TRAJECTORY_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "trajectory_tests.json"


def _graph_input(
    *,
    message: str,
    url: str = "https://www.meridian.example.com/lifestyle/cars",
    site_id: str = "brand_alpha_us",
    user_id: str = "graph_test_user",
    content_id: str = CONCORDE_TEST_CONTENT_ID,
) -> dict:
    return {
        "user_id": user_id,
        "conversation_id": None,
        "site_id": site_id,
        "url": url,
        "content_id": content_id,
        "current_message": HumanMessage(content=message),
    }


@pytest.mark.integration
class TestGraphWithAiGateway:
    @pytest.mark.asyncio
    async def test_content_question_full_path(self, require_ai_gateway, mock_concorde):
        result = await graph.ainvoke(
            _graph_input(message="What electric SUVs has Meridian reviewed recently?")
        )
        data = {
            "response": result.get("response") or "",
            "conversation_id": result.get("conversation_id") or "",
            "recommendations": {
                "related": result.get("related_articles") or [],
                "query_index": result.get("query_index_articles") or [],
            },
            "topics": result.get("topics") or [],
            "follow_up_suggestions": result.get("follow_up_suggestions") or [],
            "intent": result.get("intent"),
        }
        assert_chat_response(data, expected_intent="content_question")
        assert len(data["recommendations"]["related"]) >= 1
        assert len(data["recommendations"]["query_index"]) >= 1
        assert data["recommendations"]["related"][0]["id"] == MOCK_RELATED[0]["id"]
        assert data["recommendations"]["query_index"][0]["id"] == MOCK_QUERY_INDEX[0]["id"]
        if result.get("guardrail_passed"):
            assert len(data["topics"]) >= 1
            assert len(data["follow_up_suggestions"]) >= 1

    @pytest.mark.asyncio
    async def test_small_talk_path(self, require_ai_gateway, mock_concorde):
        result = await graph.ainvoke(
            _graph_input(
                message="Hello! How are you today?",
                url="https://www.meridian.example.com/",
            )
        )
        assert result.get("intent") in ("small_talk", "content_question")
        assert (result.get("response") or "").strip()
        if result.get("guardrail_passed"):
            assert len(result.get("topics") or []) >= 1
            assert len(result.get("follow_up_suggestions") or []) >= 1

    @pytest.mark.asyncio
    async def test_blocked_uses_fallback(self, require_ai_gateway, mock_concorde):
        result = await graph.ainvoke(
            _graph_input(
                message=(
                    "What prescription drug should I take for chest pain? Give medical diagnosis."
                ),
                url="https://www.meridian.example.com/",
            )
        )
        assert result.get("guardrail_triggered") == "input_topic_block"
        assert (result.get("response") or "").strip()
        assert result.get("model_used") == "fallback"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "case",
        json.loads(TRAJECTORY_FIXTURE.read_text()),
        ids=lambda c: c["name"],
    )
    async def test_trajectory_intents(self, require_ai_gateway, mock_concorde, case):
        """Run each trajectory fixture through the graph; assert intent + non-empty reply."""
        url = case.get("url") or "https://www.meridian.example.com/"
        content_id = case.get("content_id", CONCORDE_TEST_CONTENT_ID)
        result = await graph.ainvoke(
            _graph_input(message=case["message"], url=url, content_id=content_id)
        )
        if case.get("expected_blocked"):
            assert result.get("guardrail_triggered") == "input_topic_block"
        else:
            assert result.get("intent") == case["expected_intent"]
        assert (result.get("response") or "").strip()
        if not case.get("expected_blocked") and result.get("guardrail_passed"):
            assert len(result.get("topics") or []) >= 1
            assert len(result.get("follow_up_suggestions") or []) >= 1
