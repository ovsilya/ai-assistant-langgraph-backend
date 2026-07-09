from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from ai_assistant.llm.client import (
    _extract_json,
    _format_article_block,
    _format_output_filter,
    _split_answer_and_suggestions,
    check_output_guardrail,
)


class TestExtractJson:
    def test_parses_plain_object(self):
        assert _extract_json('{"intent": "small_talk", "reason": "greeting"}') == {
            "intent": "small_talk",
            "reason": "greeting",
        }

    def test_extracts_json_from_markdown_fence(self):
        text = 'Here you go:\n```json\n{"passed": true}\n```'
        assert _extract_json(text) == {"passed": True}

    def test_empty_input_returns_empty_dict(self):
        assert _extract_json("") == {}
        assert _extract_json("   ") == {}

    def test_invalid_json_returns_empty_dict(self):
        assert _extract_json("not json at all") == {}


class TestFormatArticleBlock:
    def test_no_articles(self):
        assert _format_article_block([]) == "(no articles)"

    def test_numbered_with_description_date_and_url(self):
        block = _format_article_block(
            [
                {
                    "title": "Lucid Gravity Review",
                    "description": "We tested it.",
                    "publish_date": "2025-01-15T00:00:00+00:00",
                    "url": "https://www.meridian.example.com/lucid",
                }
            ]
        )
        assert "cite inline as [n]" in block
        expected = "[1] Lucid Gravity Review — We tested it. — published 2025-01-15T00:00:00+00:00"
        assert expected in block
        assert "https://www.meridian.example.com/lucid" in block

    def test_includes_all_articles_no_cap(self):
        articles = [{"title": f"A{i}", "url": f"https://x/{i}"} for i in range(8)]
        block = _format_article_block(articles)
        assert "[8] A7" in block

    def test_missing_fields_fall_back(self):
        block = _format_article_block([{"id": "x"}])
        assert "[1] (untitled)" in block


class TestFormatOutputFilter:
    def test_empty(self):
        assert _format_output_filter(None) == "- (none)"
        assert _format_output_filter([]) == "- (none)"
        assert _format_output_filter({}) == "- (none)"

    def test_renders_list_of_rule_strings_as_bullets(self):
        out = _format_output_filter(
            [
                "Replies must stay grounded in the provided articles.",
                "Replies must not fabricate sources.",
            ]
        )
        assert out == (
            "- Replies must stay grounded in the provided articles.\n"
            "- Replies must not fabricate sources."
        )

    def test_dict_still_supported_for_config_ds_compat(self):
        out = _format_output_filter(
            {
                "require_content_grounding": True,
                "blocked_language_patterns": ["guaranteed cure", "100% safe"],
            }
        )
        assert "- require_content_grounding: True" in out
        assert "- blocked_language_patterns: guaranteed cure, 100% safe" in out


class TestSplitAnswerAndSuggestions:
    def test_no_delimiter_returns_whole_text_as_answer(self):
        text, topics, followups = _split_answer_and_suggestions("Just an answer, no JSON.")
        assert text == "Just an answer, no JSON."
        assert topics == []
        assert followups == []

    def test_splits_answer_from_suggestions_json(self):
        content = (
            "Here's the answer with a [1] citation.\n"
            "---SUGGESTIONS---\n"
            '{"topics": ["EVs", ""], "follow_up_suggestions": ["Which trim?", "  "]}'
        )
        text, topics, followups = _split_answer_and_suggestions(content)
        assert text == "Here's the answer with a [1] citation."
        assert topics == ["EVs"]
        assert followups == ["Which trim?"]

    def test_malformed_suggestions_json_still_keeps_answer(self):
        content = "The real answer.\n---SUGGESTIONS---\nnot json"
        text, topics, followups = _split_answer_and_suggestions(content)
        assert text == "The real answer."
        assert topics == []
        assert followups == []

    def test_suggestions_json_missing_keys_defaults_to_empty(self):
        content = 'The answer.\n---SUGGESTIONS---\n{"unrelated": "field"}'
        text, topics, followups = _split_answer_and_suggestions(content)
        assert text == "The answer."
        assert topics == []
        assert followups == []

    def test_repeated_delimiter_degrades_to_no_suggestions_not_a_crash(self):
        # A verbose model echoing the format twice shouldn't raise — the greedy
        # JSON-object regex can't cleanly isolate either block, so this degrades
        # to "no suggestions" rather than partially or incorrectly parsing one.
        content = (
            "The answer.\n"
            "---SUGGESTIONS---\n"
            '{"topics": ["A"], "follow_up_suggestions": ["Q1?"]}\n'
            "---SUGGESTIONS---\n"
            '{"topics": ["B"], "follow_up_suggestions": ["Q2?"]}'
        )
        text, topics, followups = _split_answer_and_suggestions(content)
        assert text == "The answer."
        assert isinstance(topics, list)
        assert isinstance(followups, list)


class TestCheckOutputGuardrail:
    @pytest.mark.asyncio
    async def test_missing_passed_defaults_to_fail(self, monkeypatch):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(content="not valid json")
        monkeypatch.setattr("ai_assistant.llm.client.providers.fast_llm", lambda: mock_llm)

        result = await check_output_guardrail("hello", [], False)
        assert result["passed"] is False

    @pytest.mark.asyncio
    async def test_explicit_passed_true(self, monkeypatch):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(content='{"passed": true}')
        monkeypatch.setattr("ai_assistant.llm.client.providers.fast_llm", lambda: mock_llm)

        result = await check_output_guardrail("hello", [], False)
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_explicit_passed_false(self, monkeypatch):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content='{"passed": false, "failure_type": "content_grounding_fail"}'
        )
        monkeypatch.setattr("ai_assistant.llm.client.providers.fast_llm", lambda: mock_llm)

        result = await check_output_guardrail("hello", [], True)
        assert result["passed"] is False
        assert result["failure_type"] == "content_grounding_fail"


class TestLlmClientAsyncCalls:
    @pytest.mark.asyncio
    async def test_classify_intent_and_input(self, monkeypatch):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content=(
                '{"blocked": false, "intent": "content_question", '
                '"reason": "", "resolved_query": "ev suv"}'
            )
        )
        monkeypatch.setattr("ai_assistant.llm.client.providers.fast_llm", lambda: mock_llm)

        from ai_assistant.llm.client import classify_intent_and_input

        result = await classify_intent_and_input(
            "What EVs?",
            [],
            [],
            site_id="brand_alpha_us",
        )
        assert result["intent"] == "content_question"
        assert result["blocked"] is False

    @pytest.mark.asyncio
    async def test_classify_intent_and_input_blocked_is_independent_of_intent(self, monkeypatch):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content='{"blocked": true, "intent": "off_topic", "reason": "", "resolved_query": ""}'
        )
        monkeypatch.setattr("ai_assistant.llm.client.providers.fast_llm", lambda: mock_llm)

        from ai_assistant.llm.client import classify_intent_and_input

        result = await classify_intent_and_input("...", [], [], site_id="brand_alpha_us")
        assert result["intent"] == "off_topic"
        assert result["blocked"] is True

    @pytest.mark.asyncio
    async def test_classify_intent_and_input_defaults_blocked_to_false(self, monkeypatch):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(
            content='{"intent": "small_talk", "reason": "", "resolved_query": ""}'
        )
        monkeypatch.setattr("ai_assistant.llm.client.providers.fast_llm", lambda: mock_llm)

        from ai_assistant.llm.client import classify_intent_and_input

        result = await classify_intent_and_input("hi", [], [], site_id="brand_alpha_us")
        assert result["blocked"] is False

    @pytest.mark.asyncio
    async def test_generate_answer(self, monkeypatch):
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=AIMessage(content="Answer text."))
        mock_llm.bind.return_value = mock_bound
        monkeypatch.setattr("ai_assistant.llm.client.providers.main_llm", lambda: mock_llm)
        monkeypatch.setattr("ai_assistant.llm.client.providers.provider", lambda: "ai_gateway")
        monkeypatch.setattr(
            "ai_assistant.llm.client.providers.model_main",
            lambda: "claude-sonnet-4-6",
        )

        from langchain_core.messages import HumanMessage

        from ai_assistant.llm.client import generate_answer

        result = await generate_answer(
            "You are Meridian Advisor.",
            [HumanMessage(content="What EVs?")],
            [{"title": "Lucid", "url": "https://x"}],
            site_id="brand_alpha_us",
        )
        assert result["text"] == "Answer text."
        assert result["model"]
        assert result["topics"] == []
        assert result["followups"] == []

    @pytest.mark.asyncio
    async def test_generate_answer_extracts_suggestions_from_same_call(self, monkeypatch):
        from unittest.mock import MagicMock

        content = (
            "Try the Lucid review.\n"
            "---SUGGESTIONS---\n"
            '{"topics": ["EVs"], "follow_up_suggestions": ["Which trim?"]}'
        )
        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_bound.ainvoke = AsyncMock(return_value=AIMessage(content=content))
        mock_llm.bind.return_value = mock_bound
        monkeypatch.setattr("ai_assistant.llm.client.providers.main_llm", lambda: mock_llm)
        monkeypatch.setattr("ai_assistant.llm.client.providers.provider", lambda: "ai_gateway")
        monkeypatch.setattr(
            "ai_assistant.llm.client.providers.model_main",
            lambda: "claude-sonnet-4-6",
        )

        from langchain_core.messages import HumanMessage

        from ai_assistant.llm.client import generate_answer

        result = await generate_answer(
            "You are Meridian Advisor.",
            [HumanMessage(content="What EVs?")],
            [{"title": "Lucid", "url": "https://x"}],
            content_domains="cars, culture",
            site_id="brand_alpha_us",
        )
        assert result["text"] == "Try the Lucid review."
        assert result["topics"] == ["EVs"]
        assert result["followups"] == ["Which trim?"]
        assert mock_bound.ainvoke.await_count == 1

    @pytest.mark.asyncio
    async def test_generate_title(self, monkeypatch):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = AIMessage(content='"Electric SUVs"')
        monkeypatch.setattr("ai_assistant.llm.client.providers.fast_llm", lambda: mock_llm)

        from ai_assistant.llm.client import generate_title

        title = await generate_title("What EVs has Meridian tested?", site_id="brand_alpha_us")
        assert "Electric SUVs" in title
