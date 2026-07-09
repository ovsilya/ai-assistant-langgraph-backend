"""Unit tests for LLM provider selection."""

import pytest

from ai_assistant.llm import providers


class TestProviders:
    def test_default_provider_is_ai_gateway(self, monkeypatch):
        monkeypatch.setattr(providers, "LLM_PROVIDER", "ai_gateway")
        providers.fast_llm.cache_clear()
        providers.main_llm.cache_clear()
        assert providers.provider() == "ai_gateway"
        assert providers.model_fast() == providers.AI_GATEWAY_MODEL_FAST
        assert providers.model_main() == providers.AI_GATEWAY_MODEL_MAIN

    def test_gemini_provider_uses_gemini_models(self, monkeypatch):
        monkeypatch.setattr(providers, "LLM_PROVIDER", "gemini")
        assert providers.provider() == "gemini"
        assert providers.model_fast() == providers.GEMINI_MODEL_FAST
        assert providers.max_tokens_main() == providers.GEMINI_MAX_OUTPUT_TOKENS_MAIN

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setattr(providers, "LLM_PROVIDER", "unknown")
        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            providers.provider()

    def test_build_llm_ai_gateway_path(self, monkeypatch):
        monkeypatch.setattr(providers, "LLM_PROVIDER", "ai_gateway")
        llm = providers.build_llm("claude-haiku-4-5", temperature=0.0, max_tokens=100)
        assert llm is not None
