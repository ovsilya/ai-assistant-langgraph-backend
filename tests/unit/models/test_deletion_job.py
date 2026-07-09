from ai_assistant.models import DeletionJob, DeletionJobStatus


class TestDeletionJob:
    def test_defaults(self):
        job = DeletionJob(user_id="user_abc")

        assert job.user_id == "user_abc"
        assert job.status == DeletionJobStatus.PENDING
        assert job.pending_conversation_ids == set()
        assert job.conversations_deleted == 0
        assert job.messages_deleted == 0
        assert job.attempts == 0
        assert len(job.job_id) == 26  # ULID

    def test_to_dynamo_drops_empty_pending_set(self):
        job = DeletionJob(user_id="user_abc")

        result = job.to_dynamo()

        # DynamoDB rejects empty sets.
        assert "pending_conversation_ids" not in result
        # None fields are also excluded.
        assert "ttl" not in result
        assert "lease_owner" not in result

    def test_to_dynamo_includes_non_empty_pending_set(self):
        job = DeletionJob(user_id="user_abc", pending_conversation_ids={"c1", "c2"})

        result = job.to_dynamo()

        assert result["pending_conversation_ids"] == {"c1", "c2"}

    def test_from_dynamo_round_trip_with_pending_set(self):
        job = DeletionJob(
            user_id="user_abc",
            pending_conversation_ids={"c1", "c2"},
            ttl=1_700_000_000,
        )

        restored = DeletionJob.from_dynamo(job.to_dynamo())

        assert restored == job
        assert restored.pending_conversation_ids == {"c1", "c2"}

    def test_from_dynamo_defaults_pending_when_absent(self):
        job = DeletionJob(user_id="user_abc", status=DeletionJobStatus.COMPLETE)

        restored = DeletionJob.from_dynamo(job.to_dynamo())

        assert restored.pending_conversation_ids == set()
        assert restored.status == DeletionJobStatus.COMPLETE
