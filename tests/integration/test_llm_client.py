"""Integration tests for llm/client — real internal AI gateway, no LLM mocks."""

import pytest
from langchain_core.messages import HumanMessage

from ai_assistant.llm import client
from ai_assistant.services.brand_config import load_personality


@pytest.mark.integration
class TestLlmClientWithAiGateway:
    @pytest.mark.asyncio
    async def test_classify_small_talk(self, require_ai_gateway):
        personality = load_personality("brand_alpha_us")
        result = await client.classify_intent_and_input(
            "Hello! How are you today?",
            personality["input_filter_topics"],
            personality["content_domains"],
            site_id="brand_alpha_us",
        )
        assert result["intent"] in ("small_talk", "content_question", "off_topic")

    @pytest.mark.asyncio
    async def test_classify_blocked_medical(self, require_ai_gateway):
        personality = load_personality("brand_alpha_us")
        result = await client.classify_intent_and_input(
            "What prescription drug should I take for chest pain? Give medical diagnosis.",
            personality["input_filter_topics"],
            personality["content_domains"],
            site_id="brand_alpha_us",
        )
        assert result["blocked"] is True

    @pytest.mark.asyncio
    async def test_generate_answer_uses_gateway(self, require_ai_gateway):
        personality = load_personality("brand_alpha_us")
        from tests.conftest import MOCK_QUERY_INDEX, MOCK_RELATED

        articles = MOCK_RELATED + MOCK_QUERY_INDEX
        result = await client.generate_answer(
            system_prompt=personality["system_prompt"],
            messages=[HumanMessage(content="Summarize Meridian electric SUV coverage.")],
            articles=articles,
            response_length="brief",
            max_response_tokens=256,
            page_url="https://www.meridian.example.com/lifestyle/cars",
            content_domains=", ".join(personality.get("content_domains") or []),
            site_id="brand_alpha_us",
        )
        assert result["text"].strip()
        assert "claude" in result["model"].lower() or "sonnet" in result["model"].lower()
        # Topics/follow-ups come from the same call now; assert shape, not exact content —
        # the live model isn't guaranteed to always follow the suggestions format.
        assert isinstance(result["topics"], list)
        assert isinstance(result["followups"], list)

    @pytest.mark.asyncio
    async def test_output_guardrail_uses_gateway(self, require_ai_gateway):
        personality = load_personality("brand_alpha_us")
        answer = "Meridian has covered iconic bars from New York to New Orleans."

        guard = await client.check_output_guardrail(
            answer,
            personality.get("output_filter"),
            has_articles=True,
            site_id="brand_alpha_us",
        )
        assert "passed" in guard
