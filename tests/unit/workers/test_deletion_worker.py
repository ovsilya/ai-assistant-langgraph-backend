from unittest.mock import AsyncMock, patch

from ai_assistant.constants import DELETION_JOB_LEASE_SECONDS, DELETION_JOB_MAX_ATTEMPTS
from ai_assistant.exceptions import DeletionLeaseLostError
from ai_assistant.models import DeletionJob, DeletionJobStatus
from ai_assistant.workers.deletion_worker import run_once

MODULE = "ai_assistant.workers.deletion_worker"
OWNER = "deletion-worker-test"


def _job_item(**overrides) -> dict:
    job = DeletionJob(user_id="user_abc", pending_conversation_ids={"c1"}, **overrides)
    return job.to_dynamo()


class TestRunOnce:
    async def test_claims_and_resumes_pending_job(self):
        item = _job_item()
        client = AsyncMock()
        client.get_resumable_jobs.return_value = [item]
        client.claim_deletion_job.return_value = True
        service = AsyncMock()

        completed = await run_once(service, client, OWNER)

        assert completed == 1
        client.claim_deletion_job.assert_awaited_once()
        resumed = service.resume_deletion_job.call_args.args[0]
        assert isinstance(resumed, DeletionJob)
        assert resumed.job_id == item["job_id"]
        assert service.resume_deletion_job.call_args.args[1] == OWNER

    @patch(f"{MODULE}.time.time", return_value=1000)
    async def test_claims_with_owner_and_computed_lease(self, _mock_time):
        item = _job_item()
        client = AsyncMock()
        client.get_resumable_jobs.return_value = [item]
        client.claim_deletion_job.return_value = True
        service = AsyncMock()

        await run_once(service, client, OWNER)

        client.claim_deletion_job.assert_awaited_once_with(
            item["job_id"],
            OWNER,
            1000 + DELETION_JOB_LEASE_SECONDS,
            1000,
            count_as_attempt=False,
        )

    async def test_skips_when_claim_fails(self):
        client = AsyncMock()
        client.get_resumable_jobs.return_value = [_job_item()]
        client.claim_deletion_job.return_value = False
        service = AsyncMock()

        completed = await run_once(service, client, OWNER)

        assert completed == 0
        service.resume_deletion_job.assert_not_called()

    async def test_parks_job_as_failed_after_max_attempts(self):
        item = _job_item(attempts=DELETION_JOB_MAX_ATTEMPTS)
        client = AsyncMock()
        client.get_resumable_jobs.return_value = [item]
        client.claim_deletion_job.return_value = True
        service = AsyncMock()

        completed = await run_once(service, client, OWNER)

        assert completed == 0
        client.claim_deletion_job.assert_awaited_once()
        client.finish_deletion_job.assert_awaited_once_with(
            item["job_id"], DeletionJobStatus.FAILED, OWNER
        )
        service.resume_deletion_job.assert_not_called()

    async def test_reclaiming_stale_lease_counts_as_attempt(self):
        item = _job_item(lease_owner="dead-worker", lease_expiry=123)
        client = AsyncMock()
        client.get_resumable_jobs.return_value = [item]
        client.claim_deletion_job.return_value = True
        service = AsyncMock()

        completed = await run_once(service, client, OWNER)

        assert completed == 1
        assert client.claim_deletion_job.call_args.kwargs["count_as_attempt"] is True
        service.resume_deletion_job.assert_awaited_once()

    async def test_reclaim_reaching_max_attempts_parks_without_resuming(self):
        item = _job_item(
            attempts=DELETION_JOB_MAX_ATTEMPTS - 1,
            lease_owner="dead-worker",
            lease_expiry=123,
        )
        client = AsyncMock()
        client.get_resumable_jobs.return_value = [item]
        client.claim_deletion_job.return_value = True
        service = AsyncMock()

        completed = await run_once(service, client, OWNER)

        assert completed == 0
        assert client.claim_deletion_job.call_args.kwargs["count_as_attempt"] is True
        client.finish_deletion_job.assert_awaited_once_with(
            item["job_id"], DeletionJobStatus.FAILED, OWNER
        )
        service.resume_deletion_job.assert_not_called()

    async def test_records_error_and_continues_when_resume_raises(self):
        item = _job_item()
        client = AsyncMock()
        client.get_resumable_jobs.return_value = [item]
        client.claim_deletion_job.return_value = True
        service = AsyncMock()
        service.resume_deletion_job.side_effect = RuntimeError("boom")

        completed = await run_once(service, client, OWNER)

        assert completed == 0
        client.record_deletion_job_error.assert_awaited_once_with(item["job_id"], "boom", OWNER)

    async def test_skips_error_record_when_lease_lost(self):
        item = _job_item()
        client = AsyncMock()
        client.get_resumable_jobs.return_value = [item]
        client.claim_deletion_job.return_value = True
        service = AsyncMock()
        service.resume_deletion_job.side_effect = DeletionLeaseLostError(item["job_id"])

        completed = await run_once(service, client, OWNER)

        assert completed == 0
        client.record_deletion_job_error.assert_not_called()
