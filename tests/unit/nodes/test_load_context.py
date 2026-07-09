"""Unit tests for load_context node."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_assistant.nodes.load_context import load_context
from ai_assistant.services.context_store import append_turn, ensure_conversation_id


@pytest.mark.asyncio
class TestLoadContextNode:
    async def test_loads_personality_and_assigns_conversation_id(self):
        state = {
            "site_id": "brand_alpha_us",
            "current_message": HumanMessage(content="What EVs?"),
        }
        result = await load_context(state)
        assert result["site_id"] == "brand_alpha_us"
        assert result["conversation_id"]
        assert "Meridian Advisor" in (result.get("system_prompt") or "")
        assert result.get("concorde_site_id")

    async def test_merges_history_with_current_message(self):
        conv_id = ensure_conversation_id(None)
        append_turn(conv_id, "first question", "first answer")
        state = {
            "conversation_id": conv_id,
            "site_id": "brand_alpha_us",
            "current_message": HumanMessage(content="follow up"),
        }
        result = await load_context(state)
        msgs = result["messages"]
        assert len(msgs) >= 3
        assert isinstance(msgs[-1], HumanMessage)
        assert msgs[-1].content == "follow up"
        assert any(isinstance(m, AIMessage) for m in msgs)
