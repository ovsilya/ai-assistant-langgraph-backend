"""Unit tests for assemble_response node."""

import pytest
from langchain_core.messages import HumanMessage

from ai_assistant.nodes.assemble_response import assemble_response


@pytest.mark.asyncio
class TestAssembleResponseNode:
    async def test_passed_guardrail_returns_empty(self):
        result = await assemble_response({"guardrail_passed": True})
        assert result == {}

    async def test_first_failure_adds_retry_message(self):
        result = await assemble_response(
            {
                "site_id": "brand_alpha_us",
                "guardrail_passed": False,
                "guardrail_retry_count": 0,
            }
        )
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], HumanMessage)
        assert "guardrail_retry_count" not in result

    async def test_exhausted_retries_returns_empty(self):
        result = await assemble_response(
            {
                "guardrail_passed": False,
                "guardrail_retry_count": 1,
            }
        )
        assert result == {}
