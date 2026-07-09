"""Unit tests for output_guardrail node."""

from unittest.mock import AsyncMock

import pytest

from ai_assistant.nodes.output_guardrail import output_guardrail


@pytest.mark.asyncio
class TestOutputGuardrailNode:
    async def test_passed_sets_guardrail_passed_true(self, monkeypatch):
        monkeypatch.setattr(
            "ai_assistant.nodes.output_guardrail.client.check_output_guardrail",
            AsyncMock(return_value={"passed": True}),
        )
        result = await output_guardrail(
            {
                "site_id": "brand_alpha_us",
                "response": "Grounded answer.",
                "output_filter": [],
                "related_articles": [{"id": "1"}],
            }
        )
        assert result == {"guardrail_passed": True}

    async def test_failed_sets_trigger_and_passed_false(self, monkeypatch):
        monkeypatch.setattr(
            "ai_assistant.nodes.output_guardrail.client.check_output_guardrail",
            AsyncMock(return_value={"passed": False, "failure_type": "content_grounding_fail"}),
        )
        result = await output_guardrail(
            {
                "site_id": "brand_alpha_us",
                "response": "Bad answer.",
                "output_filter": [],
            }
        )
        assert result["guardrail_passed"] is False
        assert result["guardrail_triggered"] == "content_grounding_fail"
