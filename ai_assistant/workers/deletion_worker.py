"""Background worker that polls and resumes user-data deletion jobs."""

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

from ai_assistant.clients.conversations_dynamodb import (
    ConversationsDynamoDB,
    get_conversations_dynamodb,
)
from ai_assistant.clients.dynamodb import close_dynamodb_resource, open_dynamodb_resource
from ai_assistant.constants import (
    DELETION_JOB_LEASE_SECONDS,
    DELETION_JOB_MAX_ATTEMPTS,
    DELETION_JOB_POLL_LIMIT,
    DELETION_WORKER_POLL_INTERVAL_SECONDS,
)
from ai_assistant.exceptions import DeletionLeaseLostError
from ai_assistant.models import DeletionJob, DeletionJobStatus
from ai_assistant.services.conversations_service import (
    ConversationsService,
    get_conversations_service,
)

logger = logging.getLogger(__name__)

# Touched each poll for the k8s exec probe (see deployment-deletion-worker.yml).
HEALTH_FILE = Path(os.getenv("DELETION_WORKER_HEALTH_FILE", "/tmp/deletion-worker-healthy"))


def _touch_health_file() -> None:
    try:
        HEALTH_FILE.touch()
    except OSError:
        logger.warning("could not update health file %s", HEALTH_FILE)


async def run_once(
    service: ConversationsService,
    client: ConversationsDynamoDB,
    owner: str,
) -> int:
    """Process one poll cycle. Returns the number of jobs successfully completed."""
    completed = 0
    for raw in await client.get_resumable_jobs(DELETION_JOB_POLL_LIMIT):
        _touch_health_file()
        job = DeletionJob.from_dynamo(raw)

        now_epoch = int(time.time())
        lease_expiry = now_epoch + DELETION_JOB_LEASE_SECONDS
        is_reclaim = job.lease_expiry is not None
        if not await client.claim_deletion_job(
            job.job_id, owner, lease_expiry, now_epoch, count_as_attempt=is_reclaim
        ):
            continue
        if is_reclaim:
            job.attempts += 1

        if job.attempts >= DELETION_JOB_MAX_ATTEMPTS:
            logger.error(
                "deletion job %s exceeded %d attempts; parking as FAILED",
                job.job_id,
                DELETION_JOB_MAX_ATTEMPTS,
            )
            await client.finish_deletion_job(job.job_id, DeletionJobStatus.FAILED, owner)
            continue

        try:
            await service.resume_deletion_job(job, owner)
        except* DeletionLeaseLostError:
            logger.warning("deletion job %s: lease lost to another worker; skipping", job.job_id)
        except* Exception as eg:
            cause = eg.exceptions[0]
            logger.exception("deletion job %s failed; releasing for retry", job.job_id)
            await client.record_deletion_job_error(job.job_id, str(cause), owner)
        else:
            completed += 1
            logger.info(
                "deletion job %s complete: conversations=%d messages=%d",
                job.job_id,
                job.conversations_deleted,
                job.messages_deleted,
            )
    return completed


async def main() -> None:  # pragma: no cover - process entrypoint
    owner = f"deletion-worker-{uuid.uuid4().hex[:8]}"
    await open_dynamodb_resource()
    service = get_conversations_service()
    client = get_conversations_dynamodb()
    await client.ensure_tables()
    logger.info("deletion worker %s started", owner)
    try:
        while True:
            _touch_health_file()
            try:
                await run_once(service, client, owner)
            except Exception:
                logger.exception("deletion worker poll cycle failed")
            await asyncio.sleep(DELETION_WORKER_POLL_INTERVAL_SECONDS)
    finally:
        await close_dynamodb_resource()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
