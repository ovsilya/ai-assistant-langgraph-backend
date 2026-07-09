"""Unit tests for shared node helpers."""

from ai_assistant.nodes._shared import articles_for_prompt


class TestArticlesForPrompt:
    def test_articles_combine_related_then_query_index(self):
        state = {
            "related_articles": [{"id": "r1"}],
            "query_index_articles": [{"id": "q1"}, {"id": "q2"}],
        }
        assert [a["id"] for a in articles_for_prompt(state)] == ["r1", "q1", "q2"]

    def test_articles_deduplicate_by_id(self):
        state = {
            "related_articles": [{"id": "same", "title": "Related"}],
            "query_index_articles": [{"id": "same", "title": "Dup"}, {"id": "q2"}],
        }
        assert [a["id"] for a in articles_for_prompt(state)] == ["same", "q2"]

    def test_articles_prioritize_content_id(self):
        state = {
            "content_id": "focus",
            "related_articles": [{"id": "other"}, {"id": "focus"}],
            "query_index_articles": [{"id": "q1"}],
        }
        assert [a["id"] for a in articles_for_prompt(state)] == ["focus", "other", "q1"]
