"""Unit tests for persistence stub."""

from ai_assistant.services.persistence import persist_turn


def test_persist_turn_no_op_stub():
    persist_turn({"conversation_id": "c1", "user_id": "u1"}, "hello")
