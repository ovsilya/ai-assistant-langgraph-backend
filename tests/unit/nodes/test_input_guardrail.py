"""Unit tests for input_guardrail node — mocked LLM, no ai-gateway."""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_assistant.nodes.input_guardrail import (
    _format_history,
    _title_from_url,
    input_guardrail,
)

_CLASSIFY = "ai_assistant.nodes.input_guardrail.client.classify_intent_and_input"


def _state(*, site_id: str = "brand_beta_us", message: str = "Best pasta recipes?", **extra):
    state = {
        "site_id": site_id,
        "input_filter_topics": ["medical diagnosis"],
        "content_domains": ["recipes", "cooking"],
        "messages": [HumanMessage(content=message)],
    }
    state.update(extra)
    return state


@pytest.mark.asyncio
class TestInputGuardrailNode:
    async def test_blocked_sets_guardrail_triggered(self, monkeypatch):
        monkeypatch.setattr(
            _CLASSIFY,
            AsyncMock(
                return_value={
                    "intent": "content_question",
                    "blocked": True,
                    "reason": "medical",
                    "resolved_query": "",
                }
            ),
        )
        result = await input_guardrail(_state(message="What drug for chest pain?"))
        assert result["intent"] == "content_question"
        assert result["guardrail_triggered"] == "input_topic_block"

    async def test_blocked_false_does_not_set_guardrail_triggered(self, monkeypatch):
        monkeypatch.setattr(
            _CLASSIFY,
            AsyncMock(
                return_value={
                    "intent": "off_topic",
                    "blocked": False,
                    "reason": "",
                    "resolved_query": "",
                }
            ),
        )
        result = await input_guardrail(_state(message="write me some code"))
        assert result["intent"] == "off_topic"
        assert "guardrail_triggered" not in result

    async def test_content_question_includes_resolved_query(self, monkeypatch):
        monkeypatch.setattr(
            _CLASSIFY,
            AsyncMock(
                return_value={
                    "intent": "content_question",
                    "reason": "on topic",
                    "resolved_query": "best pasta recipes",
                }
            ),
        )
        result = await input_guardrail(_state())
        assert result["intent"] == "content_question"
        assert result["resolved_query"] == "best pasta recipes"
        assert "guardrail_triggered" not in result

    async def test_invalid_intent_defaults_to_content_question(self, monkeypatch):
        monkeypatch.setattr(
            _CLASSIFY,
            AsyncMock(
                return_value={
                    "intent": "unknown_value",
                    "reason": "",
                    "resolved_query": "x",
                }
            ),
        )
        result = await input_guardrail(_state())
        assert result["intent"] == "content_question"

    async def test_passes_history_and_page_title_to_classifier(self, monkeypatch):
        mock = AsyncMock(
            return_value={
                "intent": "content_question",
                "reason": "",
                "resolved_query": "q",
            }
        )
        monkeypatch.setattr(_CLASSIFY, mock)
        state = _state(
            site_id="brand_beta_us",
            page_title="Best Pasta Ever",
            messages=[
                HumanMessage(content="What about pasta?"),
                AIMessage(content="Here are pasta recipes."),
                HumanMessage(content="Tell me more about it"),
            ],
        )
        await input_guardrail(state)
        mock.assert_awaited_once()
        kwargs = mock.await_args.kwargs
        assert kwargs["site_id"] == "brand_beta_us"
        assert kwargs["page_title"] == "Best Pasta Ever"
        assert "What about pasta?" in kwargs["conversation_history"]
        assert "Here are pasta recipes." in kwargs["conversation_history"]
        # current message is excluded from history context
        assert "Tell me more about it" not in kwargs["conversation_history"]

    async def test_page_title_derived_from_url_when_absent(self, monkeypatch):
        mock = AsyncMock(
            return_value={
                "intent": "content_question",
                "reason": "",
                "resolved_query": "q",
            }
        )
        monkeypatch.setattr(_CLASSIFY, mock)
        state = _state(url="https://www.meridian.example.com/lifestyle/cars/a61180858/lucid-gravity-review/")
        await input_guardrail(state)
        assert mock.await_args.kwargs["page_title"] == "lucid gravity review"

    async def test_resolves_site_from_settings_when_missing(self, monkeypatch):
        mock = AsyncMock(return_value={"intent": "small_talk", "reason": "", "resolved_query": ""})
        monkeypatch.setattr(_CLASSIFY, mock)
        from config import SITE_ID_DEFAULT

        state = _state()
        state.pop("site_id")
        await input_guardrail(state)
        assert mock.await_args.kwargs["site_id"] == SITE_ID_DEFAULT


class TestHelpers:
    def test_format_history_excludes_current_message(self):
        msgs = [
            HumanMessage(content="first"),
            AIMessage(content="reply"),
            HumanMessage(content="current"),
        ]
        history = _format_history(msgs)
        assert history == "User: first\nAssistant: reply"

    def test_title_from_url_homepage_is_empty(self):
        assert _title_from_url("https://www.meridian.example.com/") == ""

    def test_title_from_url_strips_id_only_last_segment(self):
        url = "https://www.meridian.example.com/lifestyle/cars/a61180858/"
        assert _title_from_url(url) == "cars"
