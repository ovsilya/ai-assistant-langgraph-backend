from os import getenv
from pathlib import Path

from dotenv import load_dotenv

# Repo root: ai-assistant/.env (same level as pyproject.toml, application.py)
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

APP_NAME = getenv("APP_NAME", "ai-assistant")
APP_VERSION = getenv("APP_VERSION", getenv("GIT_SHA", "local"))
ENVIRONMENT = getenv("ENVIRONMENT", "").lower()
HEALTHCHECK_TOKEN = getenv("HEALTHCHECK_TOKEN", "token")

AWS_DEFAULT_REGION = getenv("AWS_DEFAULT_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = getenv("AWS_SECRET_ACCESS_KEY")

CONCORDE_BASE_URL = getenv("CONCORDE_BASE_URL", "http://concorde")
CONCORDE_AI_SEARCH_BASE_URL = getenv("CONCORDE_AI_SEARCH_BASE_URL")

REDIS_HOST = getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(getenv("REDIS_PORT", "6379"))
REDIS_DB = int(getenv("REDIS_DB", "0"))

TTL_DAYS = int(getenv("TTL_DAYS", "30"))
DYNAMODB_READ_CAPACITY_UNITS = int(getenv("DYNAMODB_READ_CAPACITY_UNITS", "1"))
DYNAMODB_WRITE_CAPACITY_UNITS = int(getenv("DYNAMODB_WRITE_CAPACITY_UNITS", "1"))

DYNAMODB_ENDPOINT_URL = getenv(
    "DYNAMODB_ENDPOINT_URL",
    "https://dynamodb.us-east-1.amazonaws.com",
)
DYNAMODB_STATUS_TABLE_NAME = getenv("DYNAMODB_STATUS_TABLE_NAME", "ai-assistant-status")
DYNAMODB_CONVERSATIONS_TABLE_NAME = getenv(
    "DYNAMODB_CONVERSATIONS_TABLE_NAME", "ai_assistant_conversations"
)
DYNAMODB_MESSAGES_TABLE_NAME = getenv("DYNAMODB_MESSAGES_TABLE_NAME", "ai_assistant_messages")
DYNAMODB_DELETION_JOBS_TABLE_NAME = getenv(
    "DYNAMODB_DELETION_JOBS_TABLE_NAME", "ai_assistant_deletion_jobs"
)

DATADOG_ENABLED = getenv("DATADOG_ENABLED", "false").lower() == "true"
DATADOG_HOST = getenv("DATADOG_HOST")
ENABLE_DD_FASTAPI_INTEGRATION = getenv("ENABLE_DD_FASTAPI_INTEGRATION", "true").lower() == "true"

SENTRY_DSN = getenv("SENTRY_DSN")
SENTRY_ENVIRONMENT = getenv("SENTRY_ENVIRONMENT", ENVIRONMENT or "dev")

# --- LangGraph agent / LLM ---
GOOGLE_CLOUD_PROJECT = getenv("GOOGLE_CLOUD_PROJECT", "my-gcp-project")
GCP_LOCATION = getenv("GCP_LOCATION", "us-central1")
GOOGLE_API_KEY = getenv("GOOGLE_API_KEY", "")

LLM_PROVIDER = getenv("LLM_PROVIDER", "ai_gateway")

AI_GATEWAY_BASE_URL = getenv(
    "AI_GATEWAY_BASE_URL",
    "https://ai-gateway.internal.example.com",
)
AI_GATEWAY_API_KEY = getenv("AI_GATEWAY_API_KEY", "")
AI_GATEWAY_MODEL_FAST = getenv("AI_GATEWAY_MODEL_FAST", "claude-haiku-4-5")
AI_GATEWAY_MODEL_MAIN = getenv("AI_GATEWAY_MODEL_MAIN", "claude-sonnet-4-6")
AI_GATEWAY_MAX_OUTPUT_TOKENS_FAST = int(getenv("AI_GATEWAY_MAX_OUTPUT_TOKENS_FAST", "512"))
AI_GATEWAY_MAX_OUTPUT_TOKENS_MAIN = int(getenv("AI_GATEWAY_MAX_OUTPUT_TOKENS_MAIN", "1024"))
AI_GATEWAY_TIMEOUT = int(getenv("AI_GATEWAY_TIMEOUT", "120"))

GEMINI_MODEL_FAST = getenv("GEMINI_MODEL_FAST", "gemini-2.5-flash")
GEMINI_MODEL_MAIN = getenv("GEMINI_MODEL_MAIN", "gemini-2.5-pro")
GEMINI_MAX_OUTPUT_TOKENS_FAST = int(getenv("GEMINI_MAX_OUTPUT_TOKENS_FAST", "512"))
GEMINI_MAX_OUTPUT_TOKENS_MAIN = int(getenv("GEMINI_MAX_OUTPUT_TOKENS_MAIN", "1024"))

SITE_ID_DEFAULT = getenv("SITE_ID_DEFAULT", "brand_alpha_us")
MAX_ARTICLES = int(getenv("MAX_ARTICLES", "5"))
CHAT_CONTEXT_MESSAGES = int(getenv("CHAT_CONTEXT_MESSAGES", "6"))

# Concorde (content-search) site UUID — integration tests only. NOT a production
# fallback: each brand must set its own concorde_site_id in config/brands/*.json,
# or Concorde calls raise rather than silently borrowing another brand's content.
CONCORDE_SITE_ID = getenv("CONCORDE_SITE_ID", "")
# Sample article content id — integration tests / fixtures only (not runtime default content).
CONCORDE_TEST_CONTENT_ID = getenv(
    "CONCORDE_TEST_CONTENT_ID",
    "00000000-0000-0000-0000-000000000002",
)
CONCORDE_MAX_AGE = getenv("CONCORDE_MAX_AGE", "90d")
CONCORDE_TIMEOUT = int(getenv("CONCORDE_TIMEOUT", "30"))
