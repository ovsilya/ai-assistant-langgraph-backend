"""Shared pytest fixtures for ai-assistant."""

from __future__ import annotations

import pytest

from config import AI_GATEWAY_API_KEY, CONCORDE_SITE_ID, CONCORDE_TEST_CONTENT_ID, LLM_PROVIDER

MOCK_RELATED = [
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "title": "Meridian's Cars of the Year: The Lucid Gravity",
        "url": "https://www.meridian.example.com/lifestyle/cars/a61180858/lucid-gravity-review/",
        "description": "Our editors tested the top EVs.",
        "image_url": "https://images.example.com/example-related.jpg",
        "publish_date": "2025-01-15T00:00:00+00:00",
    },
]

MOCK_QUERY_INDEX = [
    {
        "id": "a4d5b72d-ee4c-421d-9fe6-64fdfef00e82",
        "title": "Our Hall of Fame Hotels from Around the World",
        "url": "https://www.meridian.example.com/lifestyle/a70060850/best-hotels-world/",
        "description": "Travel picks from Meridian editors.",
        "image_url": None,
        "publish_date": "2024-11-01T00:00:00+00:00",
    },
]


@pytest.fixture(scope="session")
def require_ai_gateway():
    """Skip integration tests when stage ai-gateway is unreachable or not configured."""
    from ai_assistant.llm.ai_gateway import check_reachable

    if (LLM_PROVIDER or "").strip().lower() != "ai_gateway":
        pytest.skip(f"LLM_PROVIDER={LLM_PROVIDER!r}; need ai_gateway")
    if not AI_GATEWAY_API_KEY:
        pytest.skip("AI_GATEWAY_API_KEY not set in .env")
    ok, detail = check_reachable(timeout=10.0)
    if not ok:
        pytest.skip(f"ai-gateway unreachable: {detail}")


@pytest.fixture(scope="session")
def require_concorde_site_id():
    """Skip live Concorde tests when no Concorde site UUID is configured (e.g. CI)."""
    if not CONCORDE_SITE_ID:
        pytest.skip("CONCORDE_SITE_ID not set in .env")


@pytest.fixture
def mock_concorde(monkeypatch):
    """Deterministic article cards — no Concorde HTTP in tests."""

    async def fake_query_index(site_id: str, query: str, *, concorde_site_id=None, **kwargs):
        _ = site_id, query, concorde_site_id, kwargs
        return list(MOCK_QUERY_INDEX)

    async def fake_get_related(
        site_id: str,
        *,
        concorde_site_id: str | None = None,
        content_id: str | None = None,
        page_url: str = "",
        limit: int | None = None,
    ):
        _ = site_id, concorde_site_id, page_url, limit
        if not content_id:
            return []
        return list(MOCK_RELATED)

    monkeypatch.setattr("ai_assistant.services.concorde.query_index", fake_query_index)
    monkeypatch.setattr("ai_assistant.services.concorde.get_related", fake_get_related)


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch):
    """Fresh in-memory thread per test."""
    from ai_assistant.services import context_store

    context_store._threads.clear()
    yield
    context_store._threads.clear()


@pytest.fixture
def brand_alpha_chat_payload():
    """site_id is a URL path segment now, not a body field — see api/chat.py."""
    return {
        "user_id": "test_user_1",
        "message": "What electric SUVs has Meridian reviewed?",
        "url": "https://www.meridian.example.com/lifestyle/cars/a61180858/lucid-gravity-review/",
        "content_id": CONCORDE_TEST_CONTENT_ID,
        "conversation_id": None,
    }


def assert_chat_response(data: dict, *, expected_intent: str | None = None) -> None:
    """Validate POST /v1/assistant/chat JSON shape."""
    assert isinstance(data.get("response"), str) and data["response"].strip()
    assert isinstance(data.get("conversation_id"), str) and data["conversation_id"]
    rec = data.get("recommendations") or {}
    assert isinstance(rec.get("related"), list)
    assert isinstance(rec.get("query_index"), list)
    assert isinstance(data.get("topics"), list)
    assert isinstance(data.get("follow_up_suggestions"), list)
    if expected_intent is not None:
        assert data.get("intent") == expected_intent
