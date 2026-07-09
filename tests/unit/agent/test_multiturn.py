"""Regression test for the load_context / add_messages ordering bug.

Node-level unit tests call `load_context(state)` directly and never exercise
LangGraph's actual `add_messages` reducer, so they couldn't catch this: the API
seeded `state.messages` with the current turn's message *before* `load_context`
ran, and the reducer only ever appends by id — it never reorders. The result was
`[current, *history]` instead of `[*history, current]` on every turn after the
first. This test runs the real compiled graph across two turns (mocking only the
LLM/Concorde boundary) to prove the fix holds at the level where the bug lived.
"""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage

from ai_assistant.agent.graph import graph
from ai_assistant.services.context_store import append_turn, ensure_conversation_id


def _state(*, message: str, conversation_id: str | None) -> dict:
    return {
        "user_id": "u1",
        "conversation_id": conversation_id,
        "site_id": "brand_alpha_us",
        "url": "https://www.meridian.example.com/",
        "current_message": HumanMessage(content=message),
    }


@pytest.mark.asyncio
async def test_second_turn_sees_current_message_last(monkeypatch):
    seen_messages: list[list] = []

    async def fake_classify(*args, **kwargs):
        return {"intent": "small_talk", "reason": "", "resolved_query": ""}

    async def fake_generate_answer(*, messages, **kwargs):
        seen_messages.append(list(messages))
        return {"text": "ok", "model": "m", "topics": [], "followups": []}

    monkeypatch.setattr("ai_assistant.llm.client.classify_intent_and_input", fake_classify)
    monkeypatch.setattr("ai_assistant.llm.client.generate_answer", fake_generate_answer)
    monkeypatch.setattr("ai_assistant.llm.client.generate_title", AsyncMock(return_value="Title"))
    monkeypatch.setattr(
        "ai_assistant.llm.client.check_output_guardrail",
        AsyncMock(return_value={"passed": True}),
    )

    conv_id = ensure_conversation_id(None)

    turn1 = await graph.ainvoke(_state(message="first question", conversation_id=conv_id))
    append_turn(conv_id, "first question", turn1["response"])

    await graph.ainvoke(_state(message="second question", conversation_id=conv_id))

    turn2_messages = seen_messages[-1]
    assert turn2_messages[-1].content == "second question"
    contents = [m.content for m in turn2_messages]
    assert contents.index("first question") < contents.index("second question")
