"""
Local smoke test — write and read data from both DynamoDB tables.

Not collected by pytest (requires a live DynamoDB endpoint).

Prerequisites:
    docker compose up ai-assistant-localstack -d

Run:
    LOCALSTACK_ENDPOINT_URL=http://localhost:4566 \
    AWS_DEFAULT_REGION=us-east-1 \
    AWS_ACCESS_KEY_ID=test \
    AWS_SECRET_ACCESS_KEY=test \
    ENVIRONMENT=dev \
    PYTHONPATH=. \
    uv run python scripts/smoke_test_dynamodb.py
"""

import asyncio
import uuid
from datetime import UTC, datetime

from ai_assistant.clients.conversations_dynamodb import get_conversations_dynamodb
from ai_assistant.clients.dynamodb import close_dynamodb_resource, open_dynamodb_resource
from ai_assistant.constants import DELETION_JOB_POLL_LIMIT
from ai_assistant.models import Conversation, Message
from ai_assistant.services.conversations_service import get_conversations_service
from ai_assistant.workers.deletion_worker import run_once


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _run() -> None:
    db = get_conversations_dynamodb()
    svc = get_conversations_service()
    await db.ensure_tables()

    # ------------------------------------------------------------------
    # 1. Ensure tables
    # ------------------------------------------------------------------
    print("\n--- Tables initialised ---")
    print("Tables ready.")

    # ------------------------------------------------------------------
    # 2. Multiple users with multiple conversations each
    # ------------------------------------------------------------------
    print("\n--- Writing multiple conversations for multiple users ---")
    user_a = f"user_{uuid.uuid4().hex[:8]}"
    user_b = f"user_{uuid.uuid4().hex[:8]}"

    conv_a1_id = f"conv_{uuid.uuid4().hex[:8]}"
    conv_a2_id = f"conv_{uuid.uuid4().hex[:8]}"
    conv_b1_id = f"conv_{uuid.uuid4().hex[:8]}"
    conv_b2_id = f"conv_{uuid.uuid4().hex[:8]}"

    created_at = now_iso()
    await svc.put_conversation(
        Conversation(
            user_id=user_a,
            conversation_id=conv_a1_id,
            site_id="site_001",
            title="What is the weather like today?",
            last_message_text="What is the weather like today?",
            created_at=created_at,
            last_message_at=created_at,
        )
    )
    await svc.put_messages(
        user_a,
        [
            Message(
                conversation_id=conv_a1_id,
                role="user",
                content="What is the weather like today?",
                page_url="https://example.com/weather",
                topics=["weather"],
                model_provider="ai-gateway",
                created_at=now_iso(),
            ),
            Message(
                conversation_id=conv_a1_id,
                role="assistant",
                content="Today's forecast shows sunny skies with a high of 72F.",
                topics=["weather"],
                model_provider="ai-gateway",
                model_name="gpt-4o",
                created_at=now_iso(),
            ),
        ],
    )

    created_at = now_iso()
    await svc.put_conversation(
        Conversation(
            user_id=user_a,
            conversation_id=conv_a2_id,
            site_id="site_001",
            title="Best restaurants nearby?",
            last_message_text="Best restaurants nearby?",
            created_at=created_at,
            last_message_at=created_at,
        )
    )
    await svc.put_messages(
        user_a,
        [
            Message(
                conversation_id=conv_a2_id,
                role="user",
                content="Best restaurants nearby?",
                model_provider="ai-gateway",
                created_at=now_iso(),
            ),
            Message(
                conversation_id=conv_a2_id,
                role="assistant",
                content="Here are three highly rated spots within walking distance.",
                model_provider="ai-gateway",
                model_name="gpt-4o",
                created_at=now_iso(),
            ),
        ],
    )

    created_at = now_iso()
    await svc.put_conversation(
        Conversation(
            user_id=user_b,
            conversation_id=conv_b1_id,
            site_id="site_001",
            title="How do I reset my password?",
            last_message_text="How do I reset my password?",
            created_at=created_at,
            last_message_at=created_at,
        )
    )
    await svc.put_messages(
        user_b,
        [
            Message(
                conversation_id=conv_b1_id,
                role="user",
                content="How do I reset my password?",
                model_provider="ai-gateway",
                created_at=now_iso(),
            ),
            Message(
                conversation_id=conv_b1_id,
                role="assistant",
                content="Open Settings, choose Security, then tap Reset Password.",
                model_provider="ai-gateway",
                model_name="gpt-4o",
                created_at=now_iso(),
            ),
        ],
    )

    created_at = now_iso()
    await svc.put_conversation(
        Conversation(
            user_id=user_b,
            conversation_id=conv_b2_id,
            site_id="site_001",
            title="What is DynamoDB?",
            last_message_text="What is DynamoDB?",
            created_at=created_at,
            last_message_at=created_at,
        )
    )
    await svc.put_messages(
        user_b,
        [
            Message(
                conversation_id=conv_b2_id,
                role="user",
                content="What is DynamoDB?",
                model_provider="ai-gateway",
                created_at=now_iso(),
            ),
            Message(
                conversation_id=conv_b2_id,
                role="assistant",
                content="DynamoDB is a managed NoSQL key-value and document database.",
                model_provider="ai-gateway",
                model_name="gpt-4o",
                created_at=now_iso(),
            ),
        ],
    )
    print(f"  user_a={user_a}: {conv_a1_id}, {conv_a2_id}")
    print(f"  user_b={user_b}: {conv_b1_id}, {conv_b2_id}")

    # ------------------------------------------------------------------
    # 3. Read conversations per user
    # ------------------------------------------------------------------
    print("\n--- Reading conversations for user_a ---")
    conversations_a = await svc.get_conversations(user_a)
    print(f"  Found {len(conversations_a)} conversation(s) for {user_a}:")
    for conv in conversations_a:
        print(
            f"    conversation_id={conv.conversation_id}"
            f"  title={conv.title}  message_count={conv.message_count}"
        )
    assert len(conversations_a) == 2, (
        f"user_a conversation count: expected 2, got {len(conversations_a)}"
    )

    print("\n--- Reading conversations for user_b ---")
    conversations_b = await svc.get_conversations(user_b)
    print(f"  Found {len(conversations_b)} conversation(s) for {user_b}:")
    for conv in conversations_b:
        print(
            f"    conversation_id={conv.conversation_id}"
            f"  title={conv.title}  message_count={conv.message_count}"
        )
    assert len(conversations_b) == 2, (
        f"user_b conversation count: expected 2, got {len(conversations_b)}"
    )

    # ------------------------------------------------------------------
    # 4. Read a single conversation and its messages
    # ------------------------------------------------------------------
    print("\n--- Reading single conversation and thread ---")
    conv = await svc.get_conversation_by_conversation_id(user_a, conv_a1_id)
    assert conv is not None, "conv_a1 should exist"
    print(f"  conversation_id={conv.conversation_id}  last_message_text={conv.last_message_text}")

    thread = await svc.get_messages_by_conversation(conv_a1_id)
    print(f"  Found {len(thread)} message(s) in {conv_a1_id}:")
    for msg in thread:
        print(f"    role={msg.role}  content={msg.content[:60]}")
    assert len(thread) == 2, f"conv_a1 message count: expected 2, got {len(thread)}"

    # ------------------------------------------------------------------
    # 5. User-data deletion via deletion job
    # ------------------------------------------------------------------
    async def purge_user_via_job(user_id: str, expected_conversation_ids: set[str]) -> None:
        print(f"\n--- Purging all data for {user_id} via deletion job ---")
        job_id = await svc.request_user_data_deletion(user_id)

        queued = await svc.get_deletion_job(job_id)
        assert queued is not None, "job must be persisted before any delete"
        assert queued.status.value == "PENDING", f"expected PENDING, got {queued.status}"
        assert queued.pending_conversation_ids == expected_conversation_ids, (
            "pending set must round-trip through DynamoDB as a String Set"
        )

        resumable = await db.get_resumable_jobs(DELETION_JOB_POLL_LIMIT)
        assert any(j["job_id"] == job_id for j in resumable), "job must appear in status GSI"

        completed = await run_once(svc, db, "smoke-worker")
        assert completed == 1, f"expected 1 completed job, got {completed}"

        persisted = await svc.get_deletion_job(job_id)
        assert persisted.status.value == "COMPLETE", "terminal status must be persisted"
        assert persisted.conversations_deleted == len(expected_conversation_ids)
        assert persisted.messages_deleted == 2 * len(expected_conversation_ids)
        assert persisted.pending_conversation_ids == set(), (
            "pending set must be empty (attribute dropped) after completion"
        )
        assert len(await svc.get_conversations(user_id)) == 0, (
            f"{user_id} should have no conversations after purge"
        )
        for conversation_id in expected_conversation_ids:
            assert len(await db.get_messages_by_conversation(conversation_id)) == 0, (
                f"{conversation_id} messages should be gone"
            )
        print(
            f"  Purged {user_id}: conversations={persisted.conversations_deleted} "
            f"messages={persisted.messages_deleted}"
        )

    await purge_user_via_job(user_b, {conv_b1_id, conv_b2_id})
    conversations_a = await svc.get_conversations(user_a)
    assert len(conversations_a) == 2, (
        f"user_a must be untouched by user_b purge: expected 2, got {len(conversations_a)}"
    )

    await purge_user_via_job(user_a, {conv_a1_id, conv_a2_id})

    print("\nAll reads, writes, and deletions succeeded.\n")


async def main() -> None:
    await open_dynamodb_resource()
    try:
        await _run()
    finally:
        await close_dynamodb_resource()


if __name__ == "__main__":
    asyncio.run(main())
