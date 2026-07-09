from os import getenv

AWS_DEFAULT_REGION = "us-east-1"
DYNAMODB_ENDPOINT_URL = getenv("LOCALSTACK_ENDPOINT_URL", "http://ai-assistant-localstack:4566")
DYNAMODB_STATUS_TABLE_NAME = "ai-assistant-status"
DYNAMODB_CONVERSATIONS_TABLE_NAME = "ai_assistant_conversations"
DYNAMODB_MESSAGES_TABLE_NAME = "ai_assistant_messages"
DYNAMODB_DELETION_JOBS_TABLE_NAME = "ai_assistant_deletion_jobs"
ENABLE_DD_FASTAPI_INTEGRATION = False
