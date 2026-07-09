"""LangChain clients for the internal AI gateway (LiteLLM OpenAI-compatible proxy).

Default base URL: stage (`https://ai-gateway.internal.example.com`) from `config/base.py`.
Set `AI_GATEWAY_API_KEY` in `.env` (virtual key from platform).
"""

from __future__ import annotations

from typing import Any

from config import AI_GATEWAY_API_KEY, AI_GATEWAY_BASE_URL, AI_GATEWAY_TIMEOUT


def openai_base_url() -> str:
    """LiteLLM proxy chat completions base (…/v1)."""
    base = AI_GATEWAY_BASE_URL.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def check_reachable(timeout: float = 5.0) -> tuple[bool, str]:
    """
    Probe /health/liveliness. Cached for process lifetime.
    Returns (ok, detail message).
    """
    import httpx

    url = f"{AI_GATEWAY_BASE_URL.rstrip('/')}/health/liveliness"
    try:
        resp = httpx.get(url, timeout=timeout)
        if resp.status_code == 200:
            return True, f"{url} → {resp.status_code}"
        return False, f"{url} → HTTP {resp.status_code}"
    except httpx.RequestError as e:
        return False, f"{url} unreachable: {e}"


def build_chat_model(
    model: str,
    *,
    temperature: float,
    max_tokens: int,
) -> Any:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        base_url=openai_base_url(),
        api_key=AI_GATEWAY_API_KEY or "not-set",
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=AI_GATEWAY_TIMEOUT,
    )
