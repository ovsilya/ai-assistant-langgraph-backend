from ai_assistant.llm import client
from ai_assistant.nodes._shared import articles_for_prompt
from ai_assistant.services.brand_config import site_id_from_state
from ai_assistant.state import AgentState


async def output_guardrail(state: AgentState) -> dict:
    site_id = site_id_from_state(state)
    result = await client.check_output_guardrail(
        state.get("response") or "",
        state.get("output_filter"),
        bool(articles_for_prompt(state)),
        site_id=site_id,
    )
    if result.get("passed"):
        return {"guardrail_passed": True}
    return {
        "guardrail_passed": False,
        "guardrail_triggered": result.get("failure_type") or "content_grounding_fail",
    }
