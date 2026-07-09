"""Unit tests for build_fallback node."""

import pytest

from ai_assistant.agent.intents import GUARDRAIL_INPUT_TOPIC_BLOCK
from ai_assistant.nodes.build_fallback import build_fallback


@pytest.mark.asyncio
class TestBuildFallbackNode:
    async def test_blocked_uses_blocked_prompt(self):
        result = await build_fallback(
            {
                "site_id": "brand_alpha_us",
                "guardrail_triggered": GUARDRAIL_INPUT_TOPIC_BLOCK,
            }
        )
        assert result["response"]
        assert result["guardrail_passed"] is True

    async def test_output_guardrail_failure_uses_guardrail_prompt(self):
        result = await build_fallback(
            {
                "site_id": "brand_alpha_us",
                "guardrail_triggered": "content_grounding_fail",
            }
        )
        assert result["response"]
        assert result["guardrail_passed"] is True
