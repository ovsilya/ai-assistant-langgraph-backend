"""In-memory conversation store — replace with Valkey + DynamoDB on AWS."""

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

_threads: dict[str, list] = {}


def ensure_conversation_id(conversation_id: str | None) -> str:
    return conversation_id or str(uuid4())


def get_history(conversation_id: str, limit: int = 10) -> list:
    return list(_threads.get(conversation_id, [])[-limit:])


def append_turn(conversation_id: str, user_text: str, assistant_text: str) -> None:
    msgs = _threads.setdefault(conversation_id, [])
    msgs.append(HumanMessage(content=user_text))
    msgs.append(AIMessage(content=assistant_text))
