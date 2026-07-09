from langchain_core.messages import HumanMessage
from langgraph.graph import MessagesState
from pydantic import Field

from ai_assistant.agent.intents import Intent


class AgentState(MessagesState):
    # Request context
    user_id: str = ""
    conversation_id: str | None = None
    site_id: str = ""
    url: str = ""
    page_title: str = ""  # widget document.title or URL slug fallback
    content_id: str = ""  # CMS UUID for get_related (optional)

    # The turn's raw user message. NOT part of `messages` yet — `messages` uses
    # LangGraph's add_messages reducer, which only ever appends by id, so seeding
    # it here and having load_context also fold it into history would strand it
    # at position 0 instead of chronologically after history. load_context is the
    # sole writer of `messages`; it reads this field and emits `history + [current]`.
    current_message: HumanMessage | None = None

    # Personality (loaded from config/brands/*.json; Config-DS in production)
    persona_name: str | None = None
    tone: str | None = None
    system_prompt: str | None = None
    response_length: str | None = "standard"
    content_domains: list[str] = Field(default_factory=list)
    input_filter_topics: list[str] = Field(default_factory=list)
    output_filter: list | None = None  # brand editorial rules (list or dict from Config-DS)
    max_response_tokens: int = 500
    concorde_site_id: str = ""

    # Routing
    intent: Intent | None = None
    resolved_query: str = ""  # standalone search query for Concorde query_index

    # Content — kept separate until merge logic is defined
    related_articles: list[dict] = Field(default_factory=list)
    query_index_articles: list[dict] = Field(default_factory=list)

    # Generated output
    response: str | None = None
    topics: list[str] = Field(default_factory=list)
    follow_up_suggestions: list[str] = Field(default_factory=list)
    title: str | None = None
    model_used: str | None = None

    # Guardrail
    guardrail_triggered: str | None = None
    guardrail_passed: bool = False
    guardrail_retry_count: int = 0
