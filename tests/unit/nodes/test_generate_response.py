"""Unit tests for generate_response node — mocked LLM, no ai-gateway."""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_assistant.nodes.generate_response import (
    _first_user_message,
    _is_first_turn,
    generate_response,
)

_ANSWER = "ai_assistant.nodes.generate_response.client.generate_answer"
_TITLE = "ai_assistant.nodes.generate_response.client.generate_title"


def _state(*, messages=None, **extra):
    state = {
        "site_id": "brand_alpha_us",
        "system_prompt": "You are Meridian Advisor.",
        "response_length": "standard",
        "max_response_tokens": 1024,
        "url": "https://www.meridian.example.com/lifestyle/cars",
        "messages": messages if messages is not None else [HumanMessage(content="What EVs?")],
    }
    state.update(extra)
    return state


@pytest.mark.asyncio
class TestGenerateResponseNode:
    async def test_writes_response_and_marks_guardrail_unpassed(self, monkeypatch):
        monkeypatch.setattr(
            _ANSWER,
            AsyncMock(
                return_value={
                    "text": "Here you go.",
                    "model": "claude-sonnet-4-6",
                    "topics": [],
                    "followups": [],
                }
            ),
        )
        monkeypatch.setattr(_TITLE, AsyncMock(return_value="Electric SUV Picks"))
        result = await generate_response(_state())
        assert result["response"] == "Here you go."
        assert result["model_used"] == "claude-sonnet-4-6"
        assert result["guardrail_passed"] is False

    async def test_returns_topics_and_followups_from_same_call(self, monkeypatch):
        monkeypatch.setattr(
            _ANSWER,
            AsyncMock(
                return_value={
                    "text": "Here you go.",
                    "model": "m",
                    "topics": ["EVs"],
                    "followups": ["Which trim?"],
                }
            ),
        )
        monkeypatch.setattr(_TITLE, AsyncMock(return_value="t"))
        result = await generate_response(_state())
        assert result["topics"] == ["EVs"]
        assert result["follow_up_suggestions"] == ["Which trim?"]

    async def test_first_turn_generates_llm_title(self, monkeypatch):
        answer = AsyncMock(return_value={"text": "ok", "model": "m", "topics": [], "followups": []})
        title = AsyncMock(return_value="Electric SUV Picks")
        monkeypatch.setattr(_ANSWER, answer)
        monkeypatch.setattr(_TITLE, title)
        result = await generate_response(_state())
        title.assert_awaited_once()
        assert result["title"] == "Electric SUV Picks"

    async def test_later_turn_returns_no_title(self, monkeypatch):
        answer = AsyncMock(return_value={"text": "ok", "model": "m", "topics": [], "followups": []})
        title = AsyncMock(return_value="should not be called")
        monkeypatch.setattr(_ANSWER, answer)
        monkeypatch.setattr(_TITLE, title)
        messages = [
            HumanMessage(content="What EVs?"),
            AIMessage(content="Here are some."),
            HumanMessage(content="Tell me more"),
        ]
        result = await generate_response(_state(messages=messages))
        title.assert_not_awaited()
        assert result["title"] is None

    async def test_existing_title_not_regenerated(self, monkeypatch):
        answer = AsyncMock(return_value={"text": "ok", "model": "m", "topics": [], "followups": []})
        title = AsyncMock(return_value="new")
        monkeypatch.setattr(_ANSWER, answer)
        monkeypatch.setattr(_TITLE, title)
        result = await generate_response(_state(title="Existing Title"))
        title.assert_not_awaited()
        assert result["title"] == "Existing Title"

    async def test_passes_combined_articles_to_llm(self, monkeypatch):
        answer = AsyncMock(return_value={"text": "ok", "model": "m", "topics": [], "followups": []})
        monkeypatch.setattr(_ANSWER, answer)
        monkeypatch.setattr(_TITLE, AsyncMock(return_value="t"))
        state = _state(
            related_articles=[{"id": "r1", "title": "Related"}],
            query_index_articles=[{"id": "q1", "title": "Indexed"}],
        )
        await generate_response(state)
        passed = answer.await_args.kwargs["articles"]
        assert [a["id"] for a in passed] == ["r1", "q1"]

    async def test_passes_content_domains_to_llm(self, monkeypatch):
        answer = AsyncMock(return_value={"text": "ok", "model": "m", "topics": [], "followups": []})
        monkeypatch.setattr(_ANSWER, answer)
        monkeypatch.setattr(_TITLE, AsyncMock(return_value="t"))
        await generate_response(_state(content_domains=["cars", "culture"]))
        assert answer.await_args.kwargs["content_domains"] == "cars, culture"

    async def test_guardrail_retry_increments_retry_count(self, monkeypatch):
        monkeypatch.setattr(
            _ANSWER,
            AsyncMock(
                return_value={
                    "text": "Revised.",
                    "model": "claude-sonnet-4-6",
                    "topics": [],
                    "followups": [],
                }
            ),
        )
        monkeypatch.setattr(_TITLE, AsyncMock(return_value="unused"))
        result = await generate_response(
            _state(
                response="Draft that failed.",
                guardrail_passed=False,
                guardrail_retry_count=0,
                messages=[
                    HumanMessage(content="What EVs?"),
                    HumanMessage(content="Revise using only provided articles."),
                ],
            )
        )
        assert result["response"] == "Revised."
        assert result["guardrail_retry_count"] == 1

    async def test_guardrail_retry_regenerates_matching_suggestions(self, monkeypatch):
        """Retry must return fresh topics/follow-ups for the corrected answer, not
        whatever a prior (rejected) attempt left in state — the whole point of
        generating them in the same call as the answer, not a separate node.
        """
        monkeypatch.setattr(
            _ANSWER,
            AsyncMock(
                return_value={
                    "text": "Revised.",
                    "model": "m",
                    "topics": ["Revised Topic"],
                    "followups": ["Revised follow-up?"],
                }
            ),
        )
        monkeypatch.setattr(_TITLE, AsyncMock(return_value="unused"))
        result = await generate_response(
            _state(
                response="Draft that failed.",
                guardrail_passed=False,
                guardrail_retry_count=0,
                topics=["Stale Topic"],
                follow_up_suggestions=["Stale follow-up?"],
                messages=[
                    HumanMessage(content="What EVs?"),
                    HumanMessage(content="Revise using only provided articles."),
                ],
            )
        )
        assert result["topics"] == ["Revised Topic"]
        assert result["follow_up_suggestions"] == ["Revised follow-up?"]


class TestHelpers:
    def test_is_first_turn_true_without_ai_message(self):
        assert _is_first_turn({"messages": [HumanMessage(content="hi")]}) is True

    def test_is_first_turn_false_with_ai_message(self):
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        assert _is_first_turn({"messages": msgs}) is False

    def test_first_user_message_returns_earliest_human(self):
        msgs = [
            HumanMessage(content="first"),
            AIMessage(content="x"),
            HumanMessage(content="second"),
        ]
        assert _first_user_message({"messages": msgs}) == "first"
