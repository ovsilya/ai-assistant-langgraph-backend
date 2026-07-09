"""Live Concorde HTTP tests — require network; query_index may require VPN."""

import httpx
import pytest

from ai_assistant.services.concorde import (
    get_related,
    query_index,
)
from config import CONCORDE_SITE_ID, CONCORDE_TEST_CONTENT_ID


def _skip_on_http_error(exc: Exception) -> None:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (
        403,
        502,
        503,
    ):
        pytest.skip(f"Concorde unreachable ({exc.response.status_code}) — VPN may be required")
    if isinstance(exc, httpx.HTTPError):
        pytest.skip(f"Concorde request failed: {exc}")


@pytest.mark.integration
class TestConcordeLive:
    @pytest.mark.asyncio
    async def test_get_related_brand_alpha_lucid_article(self, require_concorde_site_id):
        """Real prod get_related — Meridian Lucid Gravity article."""
        try:
            results = await get_related(
                "brand_alpha_us",
                concorde_site_id=CONCORDE_SITE_ID,
                content_id=CONCORDE_TEST_CONTENT_ID,
                limit=5,
            )
        except Exception as exc:
            _skip_on_http_error(exc)
            raise

        assert len(results) >= 1
        assert all(r["id"] and r["title"] for r in results)
        assert all(r["url"].startswith("https://") for r in results if r["url"])

    @pytest.mark.asyncio
    async def test_query_index_brand_alpha_electric_suvs(self, require_concorde_site_id):
        """Real stage query_index — search by user message."""
        try:
            results = await query_index(
                "brand_alpha_us",
                "What electric SUVs has Meridian reviewed?",
                concorde_site_id=CONCORDE_SITE_ID,
                limit=5,
            )
        except Exception as exc:
            _skip_on_http_error(exc)
            raise

        assert len(results) >= 1
        assert all(r["id"] and r["title"] for r in results)
