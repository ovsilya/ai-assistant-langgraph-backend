"""Unit tests for in-memory context_store."""

from langchain_core.messages import AIMessage, HumanMessage

from ai_assistant.services.context_store import (
    append_turn,
    ensure_conversation_id,
    get_history,
)


class TestContextStore:
    def test_ensure_conversation_id_generates_uuid_when_missing(self):
        cid = ensure_conversation_id(None)
        assert isinstance(cid, str)
        assert len(cid) > 10

    def test_ensure_conversation_id_preserves_existing(self):
        assert ensure_conversation_id("conv-123") == "conv-123"

    def test_append_and_get_history(self):
        cid = ensure_conversation_id(None)
        append_turn(cid, "hi", "hello back")
        history = get_history(cid)
        assert len(history) == 2
        assert isinstance(history[0], HumanMessage)
        assert isinstance(history[1], AIMessage)

    def test_get_history_respects_limit(self):
        cid = ensure_conversation_id(None)
        for i in range(5):
            append_turn(cid, f"u{i}", f"a{i}")
        history = get_history(cid, limit=4)
        assert len(history) == 4
