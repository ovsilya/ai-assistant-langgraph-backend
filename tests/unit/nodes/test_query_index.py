"""Unit tests for query_index node — mocked Concorde, no network."""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage

from ai_assistant.nodes.query_index import query_index_node

_QUERY_INDEX = "ai_assistant.nodes.query_index.concorde.query_index"


def _state(*, message: str, resolved_query: str | None = None):
    state = {
        "site_id": "brand_alpha_us",
        "concorde_site_id": "voltron-uuid",
        "messages": [HumanMessage(content=message)],
    }
    if resolved_query is not None:
        state["resolved_query"] = resolved_query
    return state


@pytest.mark.asyncio
class TestQueryIndexNode:
    async def test_uses_resolved_query_when_present(self, monkeypatch):
        mock = AsyncMock(return_value=[])
        monkeypatch.setattr(_QUERY_INDEX, mock)
        await query_index_node(
            _state(message="tell me more about it", resolved_query="Lucid Gravity electric SUV")
        )
        assert mock.await_args.args[1] == "Lucid Gravity electric SUV"

    async def test_falls_back_to_message_when_resolved_query_empty(self, monkeypatch):
        mock = AsyncMock(return_value=[])
        monkeypatch.setattr(_QUERY_INDEX, mock)
        await query_index_node(
            _state(message="What electric SUVs has Meridian reviewed?", resolved_query="")
        )
        assert mock.await_args.args[1] == "What electric SUVs has Meridian reviewed?"

    async def test_falls_back_to_message_when_resolved_query_absent(self, monkeypatch):
        mock = AsyncMock(return_value=[])
        monkeypatch.setattr(_QUERY_INDEX, mock)
        await query_index_node(_state(message="Best winter running shoes?"))
        assert mock.await_args.args[1] == "Best winter running shoes?"
