"""Concorde integration: query_index (search-by-message) + get_related (by content_id)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ai_assistant.clients.concorde import ConcordeClient
from config import CONCORDE_AI_SEARCH_BASE_URL, CONCORDE_BASE_URL, CONCORDE_MAX_AGE, MAX_ARTICLES

logger = logging.getLogger(__name__)

_http_client = httpx.Client(timeout=10.0)

_concorde = ConcordeClient(
    base_url=CONCORDE_BASE_URL,
    ai_search_base_url=CONCORDE_AI_SEARCH_BASE_URL or CONCORDE_BASE_URL,
    http_client=_http_client,
)


def _ensure_https(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _article_url(links: object) -> str:
    if not isinstance(links, dict):
        return ""
    web = links.get("web")
    if isinstance(web, dict):
        href = (web.get("href") or "").strip()
        if href:
            return _ensure_https(href)
    frontend = links.get("frontend")
    if isinstance(frontend, dict):
        href = (frontend.get("prod") or frontend.get("stage") or "").strip()
        if href:
            return _ensure_https(href)
    return ""


def _map_article(raw: dict) -> dict:
    images = raw.get("images_url") or raw.get("image_url")
    image_url = None
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str):
            image_url = first
        elif isinstance(first, dict):
            image_url = first.get("url")
        else:
            image_url = None
    elif isinstance(images, str):
        image_url = images

    flat_url = (raw.get("url") or "").strip()
    article_url = _ensure_https(flat_url) if flat_url else _article_url(raw.get("links"))

    return {
        "id": raw.get("id", ""),
        "title": raw.get("title") or raw.get("label") or "",
        "url": article_url,
        "description": (raw.get("description") or raw.get("dek") or "")[:300],
        "image_url": image_url,
        "publish_date": raw.get("publish_from") or raw.get("publish_date"),
    }


def _normalize_article_list(data: object) -> list[dict]:
    if isinstance(data, list):
        return [_map_article(item) for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("results", "articles", "items", "data"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [_map_article(item) for item in nested if isinstance(item, dict)]
    logger.warning("unexpected Concorde response shape: %s", type(data).__name__)
    return []


def _voltron_site_id(site_id: str, concorde_site_id: str | None = None) -> str:
    if _is_uuid(site_id):
        return site_id
    voltron = (concorde_site_id or "").strip()
    if not voltron:
        raise ValueError(
            f"No Concorde site UUID configured for site_id={site_id!r} — "
            "set concorde_site_id in its brand config (config/brands/*.json)."
        )
    return voltron


def _is_uuid(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 5 and len(value) == 36


def _query_index_sync(
    site_id: str,
    query: str,
    *,
    concorde_site_id: str | None = None,
    max_age: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    text = (query or "").strip()
    if not text:
        return []

    voltron = _voltron_site_id(site_id, concorde_site_id)
    age = max_age or CONCORDE_MAX_AGE
    n = limit or MAX_ARTICLES
    data = _concorde.query_index(voltron, text, max_age=age)
    return _normalize_article_list(data)[:n]


def _get_related_sync(
    site_id: str,
    *,
    concorde_site_id: str | None = None,
    content_id: str | None = None,
    page_url: str = "",
    limit: int | None = None,
) -> list[dict]:
    cid = (content_id or "").strip()
    if not cid:
        logger.warning("get_related skipped: content_id required (page_url=%s)", page_url)
        return []

    voltron = _voltron_site_id(site_id, concorde_site_id)
    n = limit or MAX_ARTICLES
    data: Any = _concorde.related_content(voltron, cid)
    return _normalize_article_list(data)[:n]


async def query_index(
    site_id: str,
    query: str,
    *,
    concorde_site_id: str | None = None,
    max_age: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Search articles by user message (Concorde query_index / AI search CDN)."""
    return await asyncio.to_thread(
        _query_index_sync,
        site_id,
        query,
        concorde_site_id=concorde_site_id,
        max_age=max_age,
        limit=limit,
    )


async def get_related(
    site_id: str,
    *,
    concorde_site_id: str | None = None,
    content_id: str | None = None,
    page_url: str = "",
    limit: int | None = None,
) -> list[dict]:
    """Related articles for the page the reader is on (Concorde related CDN)."""
    return await asyncio.to_thread(
        _get_related_sync,
        site_id,
        concorde_site_id=concorde_site_id,
        content_id=content_id,
        page_url=page_url,
        limit=limit,
    )
