"""Unit tests for Concorde HTTP client (mocked responses)."""

import pytest

from ai_assistant.services.concorde import (
    _map_article,
    _normalize_article_list,
    _voltron_site_id,
    get_related,
    query_index,
)
from config import CONCORDE_SITE_ID


class TestMapArticle:
    def test_maps_frontend_prod_link(self):
        raw = {
            "id": "abc-123",
            "title": "Test Article",
            "links": {
                "frontend": {
                    "prod": "https://www.meridian.example.com/lifestyle/a70060850/best-hotels-world/",
                }
            },
            "publish_from": "2025-06-01T12:00:00Z",
        }
        mapped = _map_article(raw)
        assert mapped["url"] == "https://www.meridian.example.com/lifestyle/a70060850/best-hotels-world/"
        assert mapped["id"] == "abc-123"

    def test_maps_web_href_link(self):
        raw = {
            "id": "x",
            "label": "Fallback title",
            "links": {"web": {"href": "https://www.meridian.example.com/foo"}},
        }
        mapped = _map_article(raw)
        assert mapped["title"] == "Fallback title"
        assert mapped["url"] == "https://www.meridian.example.com/foo"

    def test_maps_query_index_flat_url(self):
        raw = {
            "id": "cf2227fe-50ea-4173-81b8-bba7e5a87098",
            "title": "Electric SUV Review",
            "description": "Meridian tested the latest EVs.",
            "url": "https://www.meridian.example.com/lifestyle/cars/a61180858/lucid-gravity-review/",
            "image_url": "https://images.example.com/hmg-prod/images/example.png",
            "publish_date": "2026-04-24T11:11:00Z",
        }
        mapped = _map_article(raw)
        assert mapped["url"] == raw["url"]
        assert mapped["image_url"] == raw["image_url"]
        assert mapped["publish_date"] == raw["publish_date"]

    def test_maps_image_dict_in_list(self):
        raw = {
            "id": "1",
            "title": "T",
            "images_url": [{"url": "https://img.example/a.jpg"}],
        }
        mapped = _map_article(raw)
        assert mapped["image_url"] == "https://img.example/a.jpg"

    def test_voltron_site_id_passes_through_uuid(self):
        site_uuid = "11111111-1111-1111-1111-111111111111"
        assert _voltron_site_id(site_uuid) == site_uuid

    def test_voltron_site_id_uses_provided_concorde_site_id(self):
        assert _voltron_site_id("brand_alpha_us", concorde_site_id="brand-configured-uuid") == (
            "brand-configured-uuid"
        )

    def test_voltron_site_id_raises_when_not_configured(self):
        with pytest.raises(ValueError, match="No Concorde site UUID configured"):
            _voltron_site_id("brand_beta_us", concorde_site_id="")


class TestNormalizeArticleList:
    def test_accepts_top_level_list(self):
        items = _normalize_article_list([{"id": "1", "title": "A", "links": {}}])
        assert len(items) == 1

    def test_accepts_results_wrapper(self):
        items = _normalize_article_list({"results": [{"id": "1", "title": "A", "links": {}}]})
        assert len(items) == 1


class TestConcordeHttp:
    @pytest.mark.asyncio
    async def test_query_index_empty_query_returns_empty(self):
        assert await query_index("brand_alpha_us", "") == []

    @pytest.mark.asyncio
    async def test_query_index_builds_search_url(self, monkeypatch):
        captured = {}

        def fake_query_index_sync(
            site_id,
            query,
            *,
            concorde_site_id=None,
            max_age=None,
            limit=None,
        ):
            captured["site_id"] = site_id
            captured["query"] = query
            captured["max_age"] = max_age
            return [
                {
                    "id": "q1",
                    "title": "Electric SUV Review",
                    "url": "https://www.meridian.example.com/lifestyle/cars/ev-review/",
                }
            ]

        monkeypatch.setattr(
            "ai_assistant.services.concorde._query_index_sync",
            fake_query_index_sync,
        )

        results = await query_index(
            "brand_alpha_us",
            "What electric SUVs has Meridian reviewed?",
            concorde_site_id=CONCORDE_SITE_ID,
            limit=3,
        )
        assert results[0]["id"] == "q1"
        assert results[0]["url"] == "https://www.meridian.example.com/lifestyle/cars/ev-review/"
        assert captured["site_id"] == "brand_alpha_us"
        assert captured["query"] == "What electric SUVs has Meridian reviewed?"

    @pytest.mark.asyncio
    async def test_get_related_requires_content_id(self):
        results = await get_related("brand_alpha_us", content_id="")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_related_calls_consumer_api(self, monkeypatch):
        captured = {}

        def fake_get_related_sync(
            site_id,
            *,
            concorde_site_id=None,
            content_id=None,
            page_url="",
            limit=None,
        ):
            captured["site_id"] = site_id
            captured["content_id"] = content_id
            return [
                {
                    "id": "00000000-0000-0000-0000-000000000002",
                    "title": "Lucid Gravity",
                    "url": "https://www.meridian.example.com/lifestyle/cars/ev/",
                }
            ]

        monkeypatch.setattr(
            "ai_assistant.services.concorde._get_related_sync",
            fake_get_related_sync,
        )

        results = await get_related(
            "brand_alpha_us",
            concorde_site_id=CONCORDE_SITE_ID,
            content_id="00000000-0000-0000-0000-000000000002",
            limit=2,
        )
        assert len(results) == 1
        assert captured["site_id"] == "brand_alpha_us"
        assert captured["content_id"] == "00000000-0000-0000-0000-000000000002"
