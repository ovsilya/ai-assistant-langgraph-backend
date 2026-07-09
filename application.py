import logging
from contextlib import asynccontextmanager

import ddtrace
import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from ai_assistant.api.chat import chat_router
from ai_assistant.api.health import health_router
from ai_assistant.api.sentry_test import sentry_test_router
from ai_assistant.api.user_data import user_data_router
from ai_assistant.clients.dynamodb import close_dynamodb_resource, open_dynamodb_resource
from ai_assistant.clients.dynamodb_init import initialize_dynamodb_tables
from ai_assistant.exceptions import (
    ConversationAlreadyExistsError,
    ConversationNotFoundError,
)
from config import (
    APP_NAME,
    APP_VERSION,
    DATADOG_ENABLED,
    ENABLE_DD_FASTAPI_INTEGRATION,
    ENVIRONMENT,
    SENTRY_DSN,
)

if DATADOG_ENABLED:
    ddtrace.config.fastapi["service_name"] = APP_NAME
    ddtrace.config.fastapi["request_span_name"] = f"{APP_NAME}.request"
    ddtrace.patch(fastapi=ENABLE_DD_FASTAPI_INTEGRATION)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await open_dynamodb_resource()
        await initialize_dynamodb_tables()
        logger.info("AI Assistant server has started")
        yield
    finally:
        await close_dynamodb_resource()


swagger_enabled = ENVIRONMENT != "kubeprod"
server = FastAPI(
    title="AI Assistant",
    version=APP_VERSION,
    docs_url="/docs" if swagger_enabled else None,
    redoc_url="/redoc" if swagger_enabled else None,
    openapi_url="/openapi.json" if swagger_enabled else None,
    lifespan=lifespan,
)

server.include_router(health_router)
server.include_router(chat_router)
server.include_router(sentry_test_router)
server.include_router(user_data_router)


# ---------------------------------------------------------------------------
# Exception handler registry
# ---------------------------------------------------------------------------


@server.exception_handler(ConversationNotFoundError)
async def conversation_not_found_handler(
    request: Request,
    exc: ConversationNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": "not_found", "detail": str(exc)},
    )


@server.exception_handler(ConversationAlreadyExistsError)
async def conversation_already_exists_handler(
    request: Request,
    exc: ConversationAlreadyExistsError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": "conflict", "detail": str(exc)},
    )


server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, environment=ENVIRONMENT, release=APP_VERSION)
