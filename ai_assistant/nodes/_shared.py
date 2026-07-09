from ai_assistant.state import AgentState


def articles_for_prompt(state: AgentState) -> list[dict]:
    """Combined, de-duplicated article context — related first, current article prioritized."""
    related = state.get("related_articles") or []
    indexed = state.get("query_index_articles") or []
    content_id = (state.get("content_id") or "").strip()

    seen: set[str] = set()
    merged: list[dict] = []
    for article in related + indexed:
        aid = (article.get("id") or "").strip()
        if aid:
            if aid in seen:
                continue
            seen.add(aid)
        merged.append(article)

    if content_id:
        merged.sort(key=lambda a: 0 if (a.get("id") or "").strip() == content_id else 1)
    return merged
