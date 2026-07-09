import asyncio
import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from starlette.responses import JSONResponse

from ai_assistant.clients.conversations_dynamodb import get_conversations_dynamodb
from ai_assistant.clients.dynamodb import get_dynamodb_client
from config import ENVIRONMENT

logger = logging.getLogger(__name__)

health_router = APIRouter(
    prefix="/health",
    tags=["health"],
)


async def _run_check(
    name: str,
    table: str,
    check: Callable[[], Awaitable[None]],
) -> tuple[str, dict[str, str]]:
    try:
        await check()
        return name, {"status": "ok", "table": table}
    except Exception:
        # Log the real error server-side; never expose internal detail to callers.
        logger.exception("DynamoDB health check failed for %s (table=%s)", name, table)
        return name, {"status": "failed", "table": table}


_DYNAMODB_HEALTH_TIMEOUT_SECONDS = 5.0


@health_router.get("/")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "ok"}, status_code=200)


@health_router.get("/dynamodb")
async def check_dynamodb() -> JSONResponse:
    # Both getters are @lru_cache(maxsize=1) singletons — no new connection per request.
    dynamodb_client = get_dynamodb_client()
    conversations_client = get_conversations_dynamodb()
    try:
        checks = await asyncio.wait_for(
            asyncio.gather(
                _run_check(
                    "status_table",
                    dynamodb_client.status_table,
                    dynamodb_client.check_status_table,
                ),
                _run_check(
                    "conversations_table",
                    conversations_client.conversations_table,
                    lambda: conversations_client.check_table(
                        conversations_client.conversations_table
                    ),
                ),
                _run_check(
                    "messages_table",
                    conversations_client.messages_table,
                    lambda: conversations_client.check_table(conversations_client.messages_table),
                ),
            ),
            timeout=_DYNAMODB_HEALTH_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.error(
            "DynamoDB health check timed out after %.1fs",
            _DYNAMODB_HEALTH_TIMEOUT_SECONDS,
        )
        return JSONResponse(
            content={"status": "unhealthy", "error": "health check timed out"},
            status_code=500,
        )

    results = dict(checks)
    all_ok = all(result["status"] == "ok" for result in results.values())
    return JSONResponse(
        content={
            "status": "ok" if all_ok else "unhealthy",
            "env": ENVIRONMENT,
            "results": results,
        },
        status_code=200 if all_ok else 500,
    )
