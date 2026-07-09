"""Unit tests for ai-gateway HTTP wiring."""

from unittest.mock import MagicMock

import httpx

from ai_assistant.llm import ai_gateway


class TestOpenAiBaseUrl:
    def test_appends_v1_when_missing(self, monkeypatch):
        monkeypatch.setattr(
            ai_gateway,
            "AI_GATEWAY_BASE_URL",
            "https://ai-gateway.internal.example.com",
        )
        assert ai_gateway.openai_base_url().endswith("/v1")

    def test_preserves_existing_v1_suffix(self, monkeypatch):
        monkeypatch.setattr(
            ai_gateway,
            "AI_GATEWAY_BASE_URL",
            "https://ai-gateway.internal.example.com/v1",
        )
        assert ai_gateway.openai_base_url() == "https://ai-gateway.internal.example.com/v1"


class TestCheckReachable:
    def test_returns_true_on_200(self, monkeypatch):
        response = MagicMock(status_code=200)
        monkeypatch.setattr(httpx, "get", lambda *a, **k: response)
        ok, detail = ai_gateway.check_reachable(timeout=1.0)
        assert ok is True
        assert "200" in detail

    def test_returns_false_on_http_error(self, monkeypatch):
        response = MagicMock(status_code=503)
        monkeypatch.setattr(httpx, "get", lambda *a, **k: response)
        ok, detail = ai_gateway.check_reachable(timeout=1.0)
        assert ok is False
        assert "503" in detail

    def test_returns_false_on_network_error(self, monkeypatch):
        def raise_error(*args, **kwargs):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "get", raise_error)
        ok, detail = ai_gateway.check_reachable(timeout=1.0)
        assert ok is False
        assert "unreachable" in detail


class TestBuildChatModel:
    def test_returns_chat_openai_instance(self, monkeypatch):
        monkeypatch.setattr(ai_gateway, "AI_GATEWAY_API_KEY", "test-key")
        model = ai_gateway.build_chat_model(
            "claude-haiku-4-5",
            temperature=0.0,
            max_tokens=128,
        )
        assert model.model_name == "claude-haiku-4-5"
