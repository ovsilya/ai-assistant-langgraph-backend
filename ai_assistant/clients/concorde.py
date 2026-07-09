from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from ai_assistant.utils import retry_if_error
from config import CONCORDE_AI_SEARCH_BASE_URL, CONCORDE_BASE_URL

# Transient network errors worth retrying; HTTP 4xx/5xx propagate immediately.
_CONCORDE_RETRY_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
)


@dataclass(frozen=True)
class ConcordeClient:
    base_url: str = CONCORDE_BASE_URL
    ai_search_base_url: str | None = None
    http_client: httpx.Client | None = None

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def related_content(
        self,
        site_id: str,
        content_id: str,
        **params: Any,
    ) -> Any:
        return self._get_json(
            self.url(
                f"/v2/consumer/{quote(site_id, safe='')}/related/{quote(content_id, safe='')}"
            ),
            params=self._clean_params(params),
        )

    def query_index(
        self,
        site_id: str,
        query: str,
        max_age: str | None = None,
    ) -> Any:
        base_url = self._query_index_base_url()
        return self._get_json(
            self._join_url(
                base_url,
                f"/search/{quote(site_id, safe='')}/{quote(query, safe='')}",
            ),
            params=self._clean_params({"max_age": max_age}),
        )

    @retry_if_error(number_of_tries=3, delay=0.5, exceptions=_CONCORDE_RETRY_EXCEPTIONS)
    def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        if self.http_client is not None:
            response = self.http_client.get(url, params=params)
        else:
            response = httpx.get(url, params=params, timeout=10.0)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _join_url(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    def _query_index_base_url(self) -> str:
        if self.ai_search_base_url:
            return self.ai_search_base_url
        if self.base_url == CONCORDE_BASE_URL and CONCORDE_AI_SEARCH_BASE_URL:
            return CONCORDE_AI_SEARCH_BASE_URL
        return self.base_url

    @staticmethod
    def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in params.items() if value is not None}
