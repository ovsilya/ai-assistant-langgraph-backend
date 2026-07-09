from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str
    message: str
    url: str = ""
    page_title: str | None = None  # optional; widget document.title for reference resolution
    conversation_id: str | None = None
    content_id: str | None = None  # CMS UUID for get_related
    # site_id is a URL path parameter (e.g. Concorde's /v2/consumer/{site_id}/related/...
    # convention), not a body field — see chat_router routes in api/chat.py.


class ArticleRecommendation(BaseModel):
    id: str
    title: str
    url: str
    description: str = ""
    image_url: str | None = None
    publish_date: str | None = None


class Recommendations(BaseModel):
    related: list[ArticleRecommendation] = Field(default_factory=list)
    query_index: list[ArticleRecommendation] = Field(default_factory=list)


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    title: str | None = None
    model_used: str | None = None
    guardrail_triggered: str | None = None
    recommendations: Recommendations = Field(default_factory=Recommendations)
    topics: list[str] = Field(default_factory=list)
    follow_up_suggestions: list[str] = Field(default_factory=list)
    intent: str | None = None
