from langchain_core.messages import HumanMessage

from ai_assistant.prompts.loader import load_prompt
from ai_assistant.services.brand_config import site_id_from_state
from ai_assistant.state import AgentState


async def assemble_response(state: AgentState) -> dict:
    if state.get("guardrail_passed"):
        return {}

    if state.get("guardrail_retry_count", 0) < 1:
        site_id = site_id_from_state(state)
        corrective = HumanMessage(
            content=load_prompt("guardrail_retry_user", site=site_id),
        )
        return {"messages": [corrective]}

    return {}
