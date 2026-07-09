import re
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage

from ai_assistant.agent.intents import (
    DEFAULT_INTENT,
    GUARDRAIL_INPUT_TOPIC_BLOCK,
    VALID_INTENTS,
)
from ai_assistant.llm import client
from ai_assistant.services.brand_config import site_id_from_state
from ai_assistant.state import AgentState

# Last N messages (user + assistant) shown to the classifier purely for reference resolution.
_HISTORY_MESSAGES = 6
_HISTORY_CHAR_CAP = 1500
_ROVER_ID_RE = re.compile(r"^a?\d{6,}$")


def _last_user_text(state: AgentState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
            return msg.content if hasattr(msg, "content") else str(msg)
    return ""


def _is_human(msg: object) -> bool:
    return isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human"


def _format_history(messages: list) -> str:
    """Prior turns (excluding the current message) as plain User/Assistant lines."""
    prior = (messages[:-1] if messages else [])[-_HISTORY_MESSAGES:]
    lines = []
    for msg in prior:
        role = "User" if _is_human(msg) else "Assistant"
        content = msg.content if hasattr(msg, "content") else str(msg)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)[-_HISTORY_CHAR_CAP:]


def _title_from_url(url: str) -> str:
    """Best-effort page title from the URL slug when the widget sends no page_title.

    e.g. https://www.meridian.example.com/lifestyle/cars/a61180858/lucid-gravity-review/
    -> "lucid gravity review". Returns "" for homepages or id-only paths.
    """
    if not url:
        return ""
    segments = [s for s in urlparse(url).path.split("/") if s]
    if not segments:
        return ""
    slug = segments[-1]
    if _ROVER_ID_RE.match(slug) and len(segments) >= 2:
        slug = segments[-2]
    return slug.replace("-", " ").replace("_", " ").strip()


async def input_guardrail(state: AgentState) -> dict:
    # An empty/whitespace message is a validation concern, not a safety or intent
    # decision — the API layer (chat.py) rejects those before the graph starts,
    # so `text` here is guaranteed non-empty.
    text = _last_user_text(state)
    site_id = site_id_from_state(state)
    page_title = state.get("page_title") or _title_from_url(state.get("url") or "")

    result = await client.classify_intent_and_input(
        text,
        state.get("input_filter_topics") or [],
        state.get("content_domains") or [],
        conversation_history=_format_history(state.get("messages") or []),
        page_title=page_title,
        site_id=site_id,
    )
    intent = result["intent"]
    if intent not in VALID_INTENTS:
        intent = DEFAULT_INTENT.value

    out: dict = {"intent": intent, "resolved_query": result.get("resolved_query") or text}
    if result.get("blocked"):
        out["guardrail_triggered"] = GUARDRAIL_INPUT_TOPIC_BLOCK
    return out
