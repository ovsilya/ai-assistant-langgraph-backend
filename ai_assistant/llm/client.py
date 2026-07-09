"""LLM calls for graph nodes — backend chosen via LLM_PROVIDER in settings."""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from ai_assistant.agent.intents import DEFAULT_INTENT
from ai_assistant.llm import providers
from ai_assistant.prompts.loader import load_prompt
from ai_assistant.services.brand_config import resolve_site_id
from config import CHAT_CONTEXT_MESSAGES


def _format_article_block(articles: list[dict]) -> str:
    """Numbered, grounding-rich article list the model cites inline as [n]."""
    if not articles:
        return "(no articles)"
    lines = []
    for i, a in enumerate(articles, 1):
        title = a.get("title") or "(untitled)"
        parts = [f"[{i}] {title}"]
        desc = (a.get("description") or "").strip()
        if desc:
            parts.append(desc)
        publish_date = a.get("publish_date")
        date = publish_date.strip() if isinstance(publish_date, str) else ""
        if date:
            parts.append(f"published {date}")
        line = " — ".join(parts)
        url = (a.get("url") or "").strip()
        if url:
            line += f"\n    {url}"
        lines.append(line)
    return "Relevant articles (cite inline as [n] when you use them):\n" + "\n".join(lines)


def _format_output_filter(output_filter: list | dict | None) -> str:
    """Brand output rules as a readable bullet list (pure-LLM advisory context).

    Brand config stores a list of natural-language rule strings. A dict is also
    accepted (e.g. if Config-DS returns a structured object) and rendered as bullets.
    """
    if not output_filter:
        return "- (none)"
    if isinstance(output_filter, list):
        return "\n".join(f"- {str(rule)}" for rule in output_filter)
    if isinstance(output_filter, dict):
        lines = []
        for key, value in output_filter.items():
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)
    return f"- {output_filter}"


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


_SUGGESTIONS_DELIMITER = "---SUGGESTIONS---"


def _split_answer_and_suggestions(content: str) -> tuple[str, list[str], list[str]]:
    """Split the main answer from its trailing topics/follow-ups block.

    generate_response_context asks the model for both in one call (see
    _SUGGESTIONS_DELIMITER usage in brand prompts) so a guardrail retry
    regenerates matching suggestions instead of reusing stale ones from a
    rejected draft. If the model didn't follow the format, the whole reply
    is treated as the answer with no suggestions rather than losing it.
    """
    if _SUGGESTIONS_DELIMITER not in content:
        return content.strip(), [], []
    answer, _, tail = content.partition(_SUGGESTIONS_DELIMITER)
    data = _extract_json(tail)
    topics = [str(t).strip() for t in (data.get("topics") or []) if str(t).strip()][:3]
    followups = [
        str(q).strip() for q in (data.get("follow_up_suggestions") or []) if str(q).strip()
    ][:3]
    return answer.strip(), topics, followups


async def classify_intent_and_input(
    message: str,
    input_filter_topics: list[str],
    content_domains: list[str],
    *,
    conversation_history: str = "",
    page_title: str = "",
    site_id: str | None = None,
) -> dict:
    """Classify the current message and rewrite it into a standalone search query.

    `conversation_history` and `page_title` are context for resolving references
    (e.g. "tell me more about it"); the model classifies only the current message.
    `resolved_query` is the coreference-resolved query used by Concorde query_index.
    `blocked` (safety) and `intent` (content-routing category) are independent
    fields — a message can be any category and still be blocked.
    """
    site = resolve_site_id(site_id)
    prompt = load_prompt(
        "input_guardrail",
        site=site,
        message=message,
        input_filter_topics=str(input_filter_topics),
        content_domains=str(content_domains),
        conversation_history=conversation_history or "(none)",
        page_title=page_title or "(unknown)",
    )
    resp = await providers.fast_llm().ainvoke([HumanMessage(content=prompt)])
    data = _extract_json(resp.content)
    resolved = (data.get("resolved_query") or "").strip()
    return {
        "intent": data.get("intent", DEFAULT_INTENT.value),
        "blocked": bool(data.get("blocked", False)),
        "reason": data.get("reason", ""),
        "resolved_query": resolved or message,
    }


async def generate_answer(
    system_prompt: str,
    messages: list,
    articles: list[dict],
    *,
    response_length: str = "standard",
    max_response_tokens: int | None = None,
    page_url: str = "",
    content_domains: str = "(general)",
    site_id: str | None = None,
) -> dict:
    """Main reply plus topics/follow-ups in a single call (see _SUGGESTIONS_DELIMITER)."""
    site = resolve_site_id(site_id)
    article_block = _format_article_block(articles)

    length_hint = {
        "brief": "1-2 sentences",
        "standard": "one short paragraph",
        "detailed": "2-3 paragraphs",
    }.get(response_length, "one short paragraph")

    context = load_prompt(
        "generate_response_context",
        site=site,
        article_block=article_block,
        page_url=page_url or "(unknown)",
        length_hint=length_hint,
        content_domains=content_domains,
    )
    sys = f"{system_prompt}\n\n{context}"
    max_tokens = max_response_tokens or providers.max_tokens_main()
    llm = providers.main_llm()
    if providers.provider() == "ai_gateway":
        llm = llm.bind(max_tokens=max_tokens)
    else:
        llm = llm.bind(max_output_tokens=max_tokens)
    window = CHAT_CONTEXT_MESSAGES
    resp = await llm.ainvoke([SystemMessage(content=sys), *messages[-window:]])
    text, topics, followups = _split_answer_and_suggestions(resp.content)
    return {
        "text": text,
        "model": providers.model_main(),
        "topics": topics,
        "followups": followups,
    }


async def generate_title(message: str, *, site_id: str | None = None) -> str:
    """Short conversation thread label from the first user message (first turn only)."""
    site = resolve_site_id(site_id)
    prompt = load_prompt("thread_title", site=site, message=message[:500])
    resp = await providers.fast_llm().ainvoke([HumanMessage(content=prompt)])
    title = (resp.content or "").strip().strip('"').strip()
    return title[:80]


async def check_output_guardrail(
    response: str,
    output_filter: list | dict | None,
    has_articles: bool,
    *,
    site_id: str | None = None,
) -> dict:
    site = resolve_site_id(site_id)
    prompt = load_prompt(
        "output_guardrail",
        site=site,
        response=response[:1000],
        has_articles=str(has_articles),
        output_filter=_format_output_filter(output_filter),
    )
    resp = await providers.fast_llm().ainvoke([HumanMessage(content=prompt)])
    data = _extract_json(resp.content)
    return {"passed": bool(data.get("passed", False)), "failure_type": data.get("failure_type")}
