from langchain_core.messages import HumanMessage

from ai_assistant.services import concorde
from ai_assistant.state import AgentState


def _last_user_text(state: AgentState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
            return msg.content if hasattr(msg, "content") else str(msg)
    return ""


async def query_index_node(state: AgentState) -> dict:
    # Prefer the coreference-resolved query from input_guardrail; fall back to raw text.
    query = (state.get("resolved_query") or "").strip() or _last_user_text(state)
    articles = await concorde.query_index(
        state.get("site_id") or "",
        query,
        concorde_site_id=state.get("concorde_site_id") or "",
    )
    return {"query_index_articles": articles}
