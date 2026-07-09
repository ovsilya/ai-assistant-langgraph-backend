from ai_assistant.services import concorde
from ai_assistant.state import AgentState


async def get_related_node(state: AgentState) -> dict:
    articles = await concorde.get_related(
        state.get("site_id") or "",
        concorde_site_id=state.get("concorde_site_id") or "",
        content_id=state.get("content_id") or "",
        page_url=state.get("url") or "",
    )
    return {"related_articles": articles}
