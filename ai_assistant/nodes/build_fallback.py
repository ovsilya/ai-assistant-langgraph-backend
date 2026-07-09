from ai_assistant.agent.intents import GUARDRAIL_INPUT_TOPIC_BLOCK
from ai_assistant.prompts.loader import load_prompt
from ai_assistant.services.brand_config import site_id_from_state
from ai_assistant.state import AgentState


async def build_fallback(state: AgentState) -> dict:
    # Empty input never reaches the graph (rejected in chat.py before invocation),
    # so the only paths here are: blocked by input_guardrail, or output_guardrail
    # retries exhausted.
    site_id = site_id_from_state(state)
    blocked = state.get("guardrail_triggered") == GUARDRAIL_INPUT_TOPIC_BLOCK
    text = load_prompt("fallback_blocked" if blocked else "fallback_guardrail", site=site_id)
    return {
        "response": text,
        "guardrail_passed": True,
        "model_used": "fallback",
    }
