from ai_assistant.services.brand_config import load_personality, resolve_site_id
from ai_assistant.services.context_store import ensure_conversation_id, get_history
from ai_assistant.state import AgentState


async def load_context(state: AgentState) -> dict:
    conv_id = ensure_conversation_id(state.get("conversation_id"))
    site_id = resolve_site_id(state.get("site_id"))
    personality = load_personality(site_id)

    history = get_history(conv_id)
    current = state.get("current_message")

    updates = {
        "conversation_id": conv_id,
        "site_id": site_id,
        "persona_name": personality.get("persona_name"),
        "tone": personality.get("tone"),
        "system_prompt": personality.get("system_prompt"),
        "response_length": personality.get("response_length", "standard"),
        "content_domains": personality.get("content_domains", []),
        "input_filter_topics": personality.get("input_filter_topics", []),
        "output_filter": personality.get("output_filter"),
        "max_response_tokens": personality.get("max_response_tokens", 500),
        "concorde_site_id": personality.get("concorde_site_id") or "",
    }
    # `messages` uses the add_messages reducer (append-by-id, never reorders), and
    # `state.messages` is empty at this point (chat.py seeds `current_message`
    # instead) — so this is the one place that establishes chronological order.
    if current is not None:
        updates["messages"] = [*history, current]
    return updates
