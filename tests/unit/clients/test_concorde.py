from unittest.mock import MagicMock, patch

from ai_assistant.clients.concorde import ConcordeClient

MODULE = "ai_assistant.clients.concorde"

# ------------------------------------------------------------------
# ConcordeClient
# ------------------------------------------------------------------


class TestConcordeClient:
    def test_builds_url_without_trailing_slash(self):
        client = ConcordeClient(base_url="https://concorde.test/")

        assert client.url("/healthcheck") == "https://concorde.test/healthcheck"

    def test_fetches_related_content(self):
        http_client = MagicMock()
        response = http_client.get.return_value
        response.json.return_value = [{"id": "related-1"}]
        client = ConcordeClient(base_url="https://concorde.test", http_client=http_client)

        result = client.related_content(
            site_id="8342522f-11a7-4c85-8c15-51f36ee1d53f",
            content_id="4f548d30-7086-4bc1-816f-6eb220a87738",
            size=10,
        )

        assert result == [{"id": "related-1"}]
        http_client.get.assert_called_once_with(
            "https://concorde.test/v2/consumer/8342522f-11a7-4c85-8c15-51f36ee1d53f"
            "/related/4f548d30-7086-4bc1-816f-6eb220a87738",
            params={"size": 10},
        )
        response.raise_for_status.assert_called_once_with()

    def test_queries_ai_search_index(self):
        http_client = MagicMock()
        response = http_client.get.return_value
        response.json.return_value = [{"id": "article-1"}]
        client = ConcordeClient(
            base_url="https://concorde.test",
            ai_search_base_url="https://content-search.test",
            http_client=http_client,
        )

        result = client.query_index(
            site_id="aa00b071-9e0d-4b3d-a890-6320963aad5f",
            query="FEMA and TSA funding restored",
            max_age="90d",
        )

        assert result == [{"id": "article-1"}]
        http_client.get.assert_called_once_with(
            "https://content-search.test/search/aa00b071-9e0d-4b3d-a890-6320963aad5f"
            "/FEMA%20and%20TSA%20funding%20restored",
            params={"max_age": "90d"},
        )
        response.raise_for_status.assert_called_once_with()

    def test_omits_empty_search_params(self):
        http_client = MagicMock()
        response = http_client.get.return_value
        response.json.return_value = []
        client = ConcordeClient(base_url="https://concorde.test", http_client=http_client)

        client.query_index(site_id="site-1", query="pasta/recipes")

        http_client.get.assert_called_once_with(
            "https://concorde.test/search/site-1/pasta%2Frecipes",
            params={},
        )
        response.raise_for_status.assert_called_once_with()

    @patch(f"{MODULE}.httpx.get")
    def test_uses_module_httpx_when_no_client_injected(self, mock_get):
        mock_get.return_value.json.return_value = [{"id": "related-1"}]
        client = ConcordeClient(base_url="https://concorde.test")

        result = client.related_content(site_id="site-1", content_id="content-1")

        assert result == [{"id": "related-1"}]
        mock_get.assert_called_once_with(
            "https://concorde.test/v2/consumer/site-1/related/content-1",
            params={},
            timeout=10.0,
        )
        mock_get.return_value.raise_for_status.assert_called_once_with()

    @patch(f"{MODULE}.CONCORDE_AI_SEARCH_BASE_URL", "https://ai-search.test")
    def test_query_index_falls_back_to_configured_ai_search_url(self):
        http_client = MagicMock()
        http_client.get.return_value.json.return_value = []
        # Default base_url == CONCORDE_BASE_URL and no ai_search_base_url override,
        # so the configured CONCORDE_AI_SEARCH_BASE_URL should win.
        client = ConcordeClient(http_client=http_client)

        client.query_index(site_id="site-1", query="news")

        http_client.get.assert_called_once_with(
            "https://ai-search.test/search/site-1/news",
            params={},
        )
