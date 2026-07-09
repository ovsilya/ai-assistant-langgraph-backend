"""Unit tests for get_related node."""

from unittest.mock import AsyncMock

import pytest

from ai_assistant.nodes.get_related import get_related_node


@pytest.mark.asyncio
class TestGetRelatedNode:
    async def test_stores_related_articles_from_concorde(self, monkeypatch):
        articles = [{"id": "abc", "title": "T", "url": "https://x"}]
        monkeypatch.setattr(
            "ai_assistant.nodes.get_related.concorde.get_related",
            AsyncMock(return_value=articles),
        )
        result = await get_related_node(
            {
                "site_id": "brand_alpha_us",
                "concorde_site_id": "",
                "content_id": "00000000-0000-0000-0000-000000000002",
                "url": "https://www.meridian.example.com/foo",
            }
        )
        assert result["related_articles"] == articles
