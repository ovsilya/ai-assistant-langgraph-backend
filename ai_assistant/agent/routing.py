from typing import Literal

from langgraph.types import Send

from ai_assistant.agent.intents import GUARDRAIL_INPUT_TOPIC_BLOCK, Intent
from ai_assistant.state import AgentState


def route_after_input_guardrail(state: AgentState):
    if state.get("guardrail_triggered") == GUARDRAIL_INPUT_TOPIC_BLOCK:
        return "build_fallback"
    intent = state.get("intent")
    if intent in (Intent.SMALL_TALK, Intent.OFF_TOPIC):
        return "generate_response"
    return [
        Send("query_index", state),
        Send("get_related", state),
    ]


def route_after_assemble(
    state: AgentState,
) -> Literal["stream_output", "generate_response", "build_fallback"]:
    if state.get("guardrail_passed"):
        return "stream_output"
    if state.get("guardrail_retry_count", 0) < 1:
        return "generate_response"
    return "build_fallback"
