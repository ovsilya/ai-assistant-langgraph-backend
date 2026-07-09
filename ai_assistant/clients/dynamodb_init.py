import asyncio

from ai_assistant.clients.conversations_dynamodb import get_conversations_dynamodb
from ai_assistant.clients.dynamodb import get_dynamodb_client


async def initialize_dynamodb_tables() -> None:
    results = await asyncio.gather(
        get_dynamodb_client().provision_status_table(),
        get_conversations_dynamodb().ensure_tables(),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, BaseException)]
    if errors:
        raise ExceptionGroup("DynamoDB table initialisation failed", errors)
