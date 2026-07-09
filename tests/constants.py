from botocore.exceptions import ClientError

from config import TTL_DAYS

MOCK_TIME = 1_700_000_000
EXPECTED_TTL = MOCK_TIME + TTL_DAYS * 24 * 60 * 60

USER_ID = "user_abc123"
CONVERSATION_ID = "conv_xyz456"

CONVERSATION_DATA = {
    "user_id": USER_ID,
    "conversation_id": CONVERSATION_ID,
    "site_id": "site_001",
    "title": "Test conversation",
    "last_message_text": "Hello",
    "created_at": "2026-01-01T00:00:00+00:00",
    "last_message_at": "2026-01-02T00:00:00+00:00",
}

CONVERSATION_ITEM = {
    **CONVERSATION_DATA,
    "message_count": 0,
    "ttl": EXPECTED_TTL,
}

MESSAGE_DATA = {
    "conversation_id": CONVERSATION_ID,
    "message_id": "01JXXXXXXXXXXXXXXXXXXXXXXXXX",
    "role": "user",
    "content": "What is the weather?",
    "created_at": "2026-01-01T00:00:00+00:00",
}

MESSAGE_INPUT = {
    **MESSAGE_DATA,
    "model_provider": "ai-gateway",
}

MESSAGE_ITEM = {**MESSAGE_INPUT, "ttl": EXPECTED_TTL}

SUCCESSFUL_RESPONSE = {"ResponseMetadata": {"HTTPStatusCode": 200}}


def _client_error(code: str, operation: str, *, message: str | None = None) -> ClientError:
    """Build a botocore ClientError with the given error code."""
    return ClientError(
        {"Error": {"Code": code, "Message": message or code}},
        operation,
    )


def _transaction_canceled_error(*, conditional_check_failed: bool = False) -> ClientError:
    """Build a TransactWriteItems TransactionCanceledException.

    When *conditional_check_failed* is True, the final CancellationReason carries
    a ConditionalCheckFailed code — mirroring the conversation Update being the
    last TransactItem.
    """
    reasons = [{"Code": "None", "Message": "None"}]
    if conditional_check_failed:
        reasons.append({"Code": "ConditionalCheckFailed", "Message": "check failed"})
    return ClientError(
        {
            "Error": {
                "Code": "TransactionCanceledException",
                "Message": "Transaction cancelled",
            },
            "CancellationReasons": reasons,
        },
        "TransactWriteItems",
    )
