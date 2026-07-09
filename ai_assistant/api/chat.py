import asyncio

from fastapi import APIRouter, Response
from langchain_core.messages import HumanMessage

from ai_assistant.agent.graph import graph
from ai_assistant.agent.intents import EMPTY_INPUT_MESSAGE, GUARDRAIL_EMPTY_INPUT
from ai_assistant.api.schemas import ChatRequest, ChatResponse, Recommendations
from ai_assistant.services.brand_config import resolve_site_id
from ai_assistant.services.context_store import append_turn, ensure_conversation_id
from ai_assistant.services.persistence import persist_turn

chat_router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


def _build_initial_state(req: ChatRequest, site_id: str | None) -> dict:
    state = {
        "user_id": req.user_id,
        "conversation_id": req.conversation_id,
        "site_id": resolve_site_id(site_id),
        "url": req.url,
        "current_message": HumanMessage(content=req.message),
    }
    if req.page_title:
        state["page_title"] = req.page_title
    if req.content_id:
        state["content_id"] = req.content_id
    return state


def _empty_message_result(req: ChatRequest) -> dict:
    """An empty/whitespace-only message is a validation concern, not a safety or
    intent decision — handled here so the graph (and input_guardrail) never sees it.
    """
    return {
        "conversation_id": ensure_conversation_id(req.conversation_id),
        "response": EMPTY_INPUT_MESSAGE,
        "model_used": "fallback",
        "guardrail_triggered": GUARDRAIL_EMPTY_INPUT,
    }


def _to_response(state: dict) -> ChatResponse:
    return ChatResponse(
        response=state.get("response") or "",
        conversation_id=state.get("conversation_id") or "",
        title=state.get("title"),
        model_used=state.get("model_used"),
        guardrail_triggered=state.get("guardrail_triggered"),
        recommendations=Recommendations(
            related=state.get("related_articles") or [],
            query_index=state.get("query_index_articles") or [],
        ),
        topics=state.get("topics") or [],
        follow_up_suggestions=state.get("follow_up_suggestions") or [],
        intent=state.get("intent"),
    )


@chat_router.post("/chat/{site_id}", response_model=ChatResponse)
@chat_router.post("/chat", response_model=ChatResponse)
async def post_chat(
    req: ChatRequest, response: Response, site_id: str | None = None
) -> ChatResponse:
    is_new_conversation = not req.conversation_id
    result = (
        _empty_message_result(req)
        if not req.message.strip()
        else await graph.ainvoke(_build_initial_state(req, site_id))
    )

    await asyncio.to_thread(persist_turn, result, req.message)

    # In-memory conversation store — replace with Valkey + DynamoDB on AWS.
    append_turn(
        result["conversation_id"],
        req.message,
        result.get("response") or "",
    )

    # Concorde convention: expose the new thread's conversation_id as a response
    # header (in addition to the body field) on the first message of a thread.
    if is_new_conversation and result.get("conversation_id"):
        response.headers["Conversation_id"] = result["conversation_id"]

    return _to_response(result)
