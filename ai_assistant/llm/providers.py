"""LLM backend selection: ai_gateway (stage default) | gemini."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from config import (
    AI_GATEWAY_MAX_OUTPUT_TOKENS_FAST,
    AI_GATEWAY_MAX_OUTPUT_TOKENS_MAIN,
    AI_GATEWAY_MODEL_FAST,
    AI_GATEWAY_MODEL_MAIN,
    GCP_LOCATION,
    GEMINI_MAX_OUTPUT_TOKENS_FAST,
    GEMINI_MAX_OUTPUT_TOKENS_MAIN,
    GEMINI_MODEL_FAST,
    GEMINI_MODEL_MAIN,
    GOOGLE_API_KEY,
    GOOGLE_CLOUD_PROJECT,
    LLM_PROVIDER,
)


def provider() -> str:
    name = (LLM_PROVIDER or "ai_gateway").strip().lower()
    if name not in ("gemini", "ai_gateway"):
        raise ValueError(f"Unknown LLM_PROVIDER={name!r}. Use 'gemini' or 'ai_gateway'.")
    return name


def model_fast() -> str:
    if provider() == "ai_gateway":
        return AI_GATEWAY_MODEL_FAST
    return GEMINI_MODEL_FAST


def model_main() -> str:
    if provider() == "ai_gateway":
        return AI_GATEWAY_MODEL_MAIN
    return GEMINI_MODEL_MAIN


def max_tokens_fast() -> int:
    if provider() == "ai_gateway":
        return AI_GATEWAY_MAX_OUTPUT_TOKENS_FAST
    return GEMINI_MAX_OUTPUT_TOKENS_FAST


def max_tokens_main() -> int:
    if provider() == "ai_gateway":
        return AI_GATEWAY_MAX_OUTPUT_TOKENS_MAIN
    return GEMINI_MAX_OUTPUT_TOKENS_MAIN


def build_llm(model: str, *, temperature: float, max_tokens: int) -> Any:
    if provider() == "ai_gateway":
        from ai_assistant.llm.ai_gateway import build_chat_model

        return build_chat_model(model, temperature=temperature, max_tokens=max_tokens)

    if GOOGLE_API_KEY:
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=GOOGLE_API_KEY,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
    return ChatGoogleGenerativeAI(
        model=model,
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GCP_LOCATION,
        temperature=temperature,
        max_output_tokens=max_tokens,
    )


@lru_cache
def fast_llm():
    return build_llm(
        model_fast(),
        temperature=0.0,
        max_tokens=max_tokens_fast(),
    )


@lru_cache
def main_llm():
    return build_llm(
        model_main(),
        temperature=0.7,
        max_tokens=max_tokens_main(),
    )
