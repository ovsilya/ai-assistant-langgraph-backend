from langchain_core.messages import AIMessage, HumanMessage

from ai_assistant.llm import client
from ai_assistant.nodes._shared import articles_for_prompt
from ai_assistant.services.brand_config import site_id_from_state
from ai_assistant.state import AgentState


def _first_user_message(state: AgentState) -> str:
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def _is_first_turn(state: AgentState) -> bool:
    """No assistant message in history yet → this is the opening turn of the thread."""
    return not any(isinstance(msg, AIMessage) for msg in state.get("messages", []))


def _is_guardrail_retry(state: AgentState) -> bool:
    """Regenerate after output guardrail failure (assemble appended retry nudge)."""
    return bool((state.get("response") or "").strip()) and not state.get("guardrail_passed")


async def generate_response(state: AgentState) -> dict:
    site_id = site_id_from_state(state)
    domains = state.get("content_domains") or []
    result = await client.generate_answer(
        system_prompt=state.get("system_prompt") or "",
        messages=state.get("messages", []),
        articles=articles_for_prompt(state),
        response_length=state.get("response_length") or "standard",
        max_response_tokens=state.get("max_response_tokens"),
        page_url=state.get("url") or "",
        content_domains=", ".join(domains) if domains else "(general)",
        site_id=site_id,
    )

    # Title is a thread label: generate once, on the first turn only (null afterwards).
    title = state.get("title")
    if not title and _is_first_turn(state):
        first_message = _first_user_message(state)
        if first_message:
            title = await client.generate_title(first_message, site_id=site_id)

    out: dict = {
        "response": result["text"],
        "model_used": result["model"],
        "title": title,
        "topics": result["topics"],
        "follow_up_suggestions": result["followups"],
        "guardrail_passed": False,
    }
    if _is_guardrail_retry(state):
        out["guardrail_retry_count"] = state.get("guardrail_retry_count", 0) + 1
    return out
