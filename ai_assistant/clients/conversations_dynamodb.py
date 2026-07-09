import logging
import time
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ai_assistant.clients.dynamodb import (
    create_table_if_absent,
    get_dynamodb_resource,
    wait_for_table_active,
)
from ai_assistant.constants import (
    DELETION_JOB_MAX_ERROR_LENGTH,
    DELETION_JOB_RECORD_TTL_DAYS,
    DELETION_JOB_STATUS_INDEX,
    DYNAMODB_PROVISIONED_THROUGHPUT,
    QUERY_PAGE_MAX,
    QUERY_PAGE_WARNING_THRESHOLD,
)
from ai_assistant.exceptions import DeletionLeaseLostError
from ai_assistant.models import DeletionJobStatus
from ai_assistant.utils.datetime_utils import utc_now_iso
from config import (
    DYNAMODB_CONVERSATIONS_TABLE_NAME,
    DYNAMODB_DELETION_JOBS_TABLE_NAME,
    DYNAMODB_MESSAGES_TABLE_NAME,
)

logger = logging.getLogger(__name__)

_CONVERSATION_UPDATE_EXPRESSION = (
    "SET last_message_at=:last_message_at, "
    "last_message_text=:last_message_text, "
    "#ttl=:ttl ADD message_count :message_count"
)
_CONVERSATION_UPDATE_ATTRIBUTE_NAMES = {"#ttl": "ttl"}


class ConversationsDynamoDB:
    def __init__(
        self,
        conversations_table: str = DYNAMODB_CONVERSATIONS_TABLE_NAME,
        messages_table: str = DYNAMODB_MESSAGES_TABLE_NAME,
        deletion_jobs_table: str = DYNAMODB_DELETION_JOBS_TABLE_NAME,
    ) -> None:
        self.conversations_table = conversations_table
        self.messages_table = messages_table
        self.deletion_jobs_table = deletion_jobs_table

    @property
    def _resource(self) -> Any:
        resource = get_dynamodb_resource()
        if resource is None:
            raise RuntimeError(
                "DynamoDB resource is not initialized — "
                "ensure open_dynamodb_resource() has been called before using this client."
            )
        return resource

    async def _get_conversations(self) -> Any:
        return await self._resource.Table(self.conversations_table)

    async def _get_messages(self) -> Any:
        return await self._resource.Table(self.messages_table)

    async def _get_deletion_jobs(self) -> Any:
        return await self._resource.Table(self.deletion_jobs_table)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _enable_ttl(self, table_name: str, ttl_attribute: str) -> None:
        try:
            await self._resource.meta.client.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification={
                    "Enabled": True,
                    "AttributeName": ttl_attribute,
                },
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ValidationException":
                message = e.response["Error"].get("Message", "")
                if "already enabled" in message.lower():
                    return
            raise

    async def _iter_query_pages(
        self,
        table: Any,
        *,
        truncate_on_page_limit: bool = False,
        **query_kwargs: Any,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        pages = 0
        warned = False
        pagination_kwargs = dict(query_kwargs)
        while True:
            pages += 1
            if pages > QUERY_PAGE_MAX:
                message = (
                    f"DynamoDB query exceeded {QUERY_PAGE_MAX} pages; "
                    "pagination may be stuck or result set is too large"
                )
                if truncate_on_page_limit:
                    logger.error("%s; returning partial results", message)
                    break
                raise RuntimeError(message)
            if pages > QUERY_PAGE_WARNING_THRESHOLD and not warned:
                logger.warning(
                    "DynamoDB query paginated past %s pages",
                    QUERY_PAGE_WARNING_THRESHOLD,
                )
                warned = True

            response = await table.query(**pagination_kwargs)
            items = response.get("Items", [])
            if items:
                yield items
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            pagination_kwargs = {**pagination_kwargs, "ExclusiveStartKey": last_key}

    async def _query_all(self, table: Any, **query_kwargs: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        async for page_items in self._iter_query_pages(
            table,
            truncate_on_page_limit=True,
            **query_kwargs,
        ):
            items.extend(page_items)
        return items

    # ------------------------------------------------------------------
    # Conversations CRUD
    # ------------------------------------------------------------------

    async def get_conversation_by_conversation_id(
        self,
        user_id: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """Return the raw DynamoDB item, or None if not found."""
        table = await self._get_conversations()
        response = await table.get_item(
            Key={"user_id": user_id, "conversation_id": conversation_id},
        )
        return response.get("Item")

    async def get_conversations(self, user_id: str) -> list[dict[str, Any]]:
        """Return raw DynamoDB items for all conversations belonging to *user_id*.

        Truncates after :data:`QUERY_PAGE_MAX` pages. For a full id list, use
        :meth:`get_all_conversation_ids`.
        """
        table = await self._get_conversations()
        return await self._query_all(
            table,
            KeyConditionExpression=Key("user_id").eq(user_id),
        )

    async def get_all_conversation_ids(self, user_id: str) -> set[str]:
        """Return every conversation id for *user_id*."""
        table = await self._get_conversations()
        ids: set[str] = set()
        async for page_items in self._iter_query_pages(
            table,
            KeyConditionExpression=Key("user_id").eq(user_id),
            ProjectionExpression="conversation_id",
        ):
            for item in page_items:
                ids.add(item["conversation_id"])
        return ids

    async def put_conversation(self, item: dict[str, Any]) -> dict:
        """Store a conversation item verbatim.

        The caller is responsible for all fields, including TTL.
        Raises :class:`~botocore.exceptions.ClientError` on failure — the caller
        should translate DynamoDB condition errors into domain exceptions.
        """
        table = await self._get_conversations()
        return await table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(conversation_id)",
        )

    async def update_conversation(
        self,
        user_id: str,
        conversation_id: str,
        last_message_at: str,
        last_message_text: str,
        message_count_delta: int,
        ttl: int,
    ) -> dict:
        """Update conversation metadata.

        *message_count_delta* is added to the stored ``message_count`` via a
        DynamoDB ``ADD`` (it is an increment, not an absolute total).

        Raises :class:`~botocore.exceptions.ClientError` on failure — the caller
        should translate DynamoDB condition errors into domain exceptions.
        """
        table = await self._get_conversations()
        return await table.update_item(
            Key={"user_id": user_id, "conversation_id": conversation_id},
            UpdateExpression=_CONVERSATION_UPDATE_EXPRESSION,
            ExpressionAttributeNames=_CONVERSATION_UPDATE_ATTRIBUTE_NAMES,
            ExpressionAttributeValues={
                ":last_message_at": last_message_at,
                ":last_message_text": last_message_text,
                ":ttl": ttl,
                ":message_count": message_count_delta,
            },
            ConditionExpression="attribute_exists(conversation_id)",
            ReturnValues="UPDATED_NEW",
        )

    async def delete_conversations_by_ids(
        self,
        user_id: str,
        conversation_ids: list[str],
    ) -> int:
        """Delete conversation rows by id. Returns the number of ids processed."""
        if not conversation_ids:
            return 0
        table = await self._get_conversations()
        async with table.batch_writer() as batch:
            for conversation_id in conversation_ids:
                await batch.delete_item(
                    Key={"user_id": user_id, "conversation_id": conversation_id}
                )
        return len(conversation_ids)

    async def transact_write_items(self, transact_items: list[dict[str, Any]]) -> dict:
        """Execute a DynamoDB TransactWriteItems call with the given items."""
        return await self._resource.meta.client.transact_write_items(TransactItems=transact_items)

    async def put_messages_transaction(
        self,
        user_id: str,
        conversation_id: str,
        message_items: list[dict[str, Any]],
        last_message_at: str,
        last_message_text: str,
        message_count: int,
        ttl: int,
    ) -> dict:
        """Atomically write messages and update their parent conversation.

        *message_items* are fully serialized DynamoDB item dicts (TTL already
        applied by the caller). This method owns the TransactWriteItems shape —
        building one Put per message followed by the conversation Update — and
        delegates execution to :meth:`transact_write_items`.

        The conversation Update is always appended last, so callers translating a
        ``TransactionCanceledException`` can rely on the final CancellationReason
        corresponding to its condition check.

        Raises :class:`~botocore.exceptions.ClientError` on failure — the caller
        should translate DynamoDB condition errors into domain exceptions.
        """
        transact_items: list[dict[str, Any]] = [
            {"Put": {"TableName": self.messages_table, "Item": item}} for item in message_items
        ]
        transact_items.append(
            {
                "Update": {
                    "TableName": self.conversations_table,
                    "Key": {
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                    },
                    "UpdateExpression": _CONVERSATION_UPDATE_EXPRESSION,
                    "ExpressionAttributeNames": _CONVERSATION_UPDATE_ATTRIBUTE_NAMES,
                    "ExpressionAttributeValues": {
                        ":last_message_at": last_message_at,
                        ":last_message_text": last_message_text,
                        ":ttl": ttl,
                        ":message_count": message_count,
                    },
                    "ConditionExpression": "attribute_exists(conversation_id)",
                },
            },
        )
        return await self.transact_write_items(transact_items)

    # ------------------------------------------------------------------
    # Messages CRUD
    # ------------------------------------------------------------------

    async def get_messages_by_conversation(
        self,
        conversation_id: str,
        scan_index_forward: bool = False,
    ) -> list[dict[str, Any]]:
        """Return raw DynamoDB items for all messages in a conversation."""
        table = await self._get_messages()
        return await self._query_all(
            table,
            KeyConditionExpression=Key("conversation_id").eq(conversation_id),
            ScanIndexForward=scan_index_forward,
        )

    async def delete_messages_by_conversation(self, conversation_id: str) -> int:
        table = await self._get_messages()
        message_keys: list[dict[str, str]] = []
        async for page_items in self._iter_query_pages(
            table,
            KeyConditionExpression=Key("conversation_id").eq(conversation_id),
        ):
            for item in page_items:
                message_keys.append(
                    {
                        "conversation_id": item["conversation_id"],
                        "message_id": item["message_id"],
                    }
                )
        if not message_keys:
            return 0
        async with table.batch_writer() as batch:
            for key in message_keys:
                await batch.delete_item(Key=key)
        return len(message_keys)

    # ------------------------------------------------------------------
    # Deletion jobs
    # ------------------------------------------------------------------

    async def put_deletion_job(self, item: dict[str, Any]) -> dict:
        """Store a new deletion-job record. Fails if the job id already exists."""
        table = await self._get_deletion_jobs()
        return await table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(job_id)",
        )

    async def get_deletion_job(self, job_id: str) -> dict[str, Any] | None:
        table = await self._get_deletion_jobs()
        response = await table.get_item(Key={"job_id": job_id})
        return response.get("Item")

    async def get_resumable_jobs(self, limit: int) -> list[dict[str, Any]]:
        """Return in-flight (PENDING/IN_PROGRESS) jobs via the status GSI, oldest first."""
        table = await self._get_deletion_jobs()
        items: list[dict[str, Any]] = []
        for status in (DeletionJobStatus.PENDING, DeletionJobStatus.IN_PROGRESS):
            response = await table.query(
                IndexName=DELETION_JOB_STATUS_INDEX,
                KeyConditionExpression=Key("status").eq(status.value),
                Limit=limit,
            )
            items.extend(response.get("Items", []))
        return items

    async def claim_deletion_job(
        self,
        job_id: str,
        owner: str,
        lease_expiry: int,
        now_epoch: int,
        count_as_attempt: bool = False,
    ) -> bool:
        """Take the lease when none is held. Returns whether the update succeeded.

        When *count_as_attempt* is true, also increments ``attempts``.
        """
        table = await self._get_deletion_jobs()
        update_expression = "SET lease_owner=:owner, lease_expiry=:exp, updated_at=:now"
        values: dict[str, Any] = {
            ":owner": owner,
            ":exp": lease_expiry,
            ":now": utc_now_iso(),
            ":now_s": now_epoch,
            ":pending": DeletionJobStatus.PENDING.value,
            ":in_progress": DeletionJobStatus.IN_PROGRESS.value,
        }
        if count_as_attempt:
            update_expression += " ADD attempts :one"
            values[":one"] = 1
        try:
            await table.update_item(
                Key={"job_id": job_id},
                UpdateExpression=update_expression,
                ConditionExpression=(
                    "attribute_exists(job_id) AND "
                    "#status IN (:pending, :in_progress) AND "
                    "(attribute_not_exists(lease_expiry) OR lease_expiry < :now_s)"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=values,
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    _LEASE_GUARD = "lease_owner = :owner"

    async def set_deletion_job_in_progress(
        self,
        job_id: str,
        conversations_deleted: int,
        owner: str,
    ) -> dict:
        table = await self._get_deletion_jobs()
        try:
            return await table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #status=:s, conversations_deleted=:c, updated_at=:now",
                ConditionExpression=self._LEASE_GUARD,
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":s": DeletionJobStatus.IN_PROGRESS.value,
                    ":c": conversations_deleted,
                    ":now": utc_now_iso(),
                    ":owner": owner,
                },
            )
        except ClientError as e:
            raise self._lease_error_or_reraise(e, job_id) from e

    async def checkpoint_conversation_deleted(
        self,
        job_id: str,
        conversation_id: str,
        messages_deleted_delta: int,
        owner: str,
    ) -> dict:
        """Remove *conversation_id* from ``pending_conversation_ids`` and add
        *messages_deleted_delta* to ``messages_deleted``."""
        table = await self._get_deletion_jobs()
        try:
            return await table.update_item(
                Key={"job_id": job_id},
                UpdateExpression=(
                    "SET updated_at=:now "
                    "ADD messages_deleted :m DELETE pending_conversation_ids :ids"
                ),
                ConditionExpression=self._LEASE_GUARD,
                ExpressionAttributeValues={
                    ":now": utc_now_iso(),
                    ":m": messages_deleted_delta,
                    ":ids": {conversation_id},
                    ":owner": owner,
                },
            )
        except ClientError as e:
            raise self._lease_error_or_reraise(e, job_id) from e

    async def finish_deletion_job(
        self,
        job_id: str,
        status: DeletionJobStatus,
        owner: str,
    ) -> dict:
        """Set terminal *status*, set ``ttl``, and remove ``lease_owner`` / ``lease_expiry``."""
        table = await self._get_deletion_jobs()
        retention_ttl = int(time.time()) + DELETION_JOB_RECORD_TTL_DAYS * 24 * 60 * 60
        try:
            return await table.update_item(
                Key={"job_id": job_id},
                UpdateExpression=(
                    "SET #status=:s, updated_at=:now, #ttl=:ttl REMOVE lease_owner, lease_expiry"
                ),
                ConditionExpression=self._LEASE_GUARD,
                ExpressionAttributeNames={"#status": "status", "#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":s": status.value,
                    ":now": utc_now_iso(),
                    ":ttl": retention_ttl,
                    ":owner": owner,
                },
            )
        except ClientError as e:
            raise self._lease_error_or_reraise(e, job_id) from e

    async def record_deletion_job_error(self, job_id: str, error: str, owner: str) -> None:
        """Increment ``attempts``, set ``last_error``, and remove lease fields.

        No-op when the lease guard fails.
        """
        table = await self._get_deletion_jobs()
        try:
            await table.update_item(
                Key={"job_id": job_id},
                UpdateExpression=(
                    "SET last_error=:e, updated_at=:now "
                    "ADD attempts :one REMOVE lease_owner, lease_expiry"
                ),
                ConditionExpression=self._LEASE_GUARD,
                ExpressionAttributeValues={
                    ":e": error[:DELETION_JOB_MAX_ERROR_LENGTH],
                    ":now": utc_now_iso(),
                    ":one": 1,
                    ":owner": owner,
                },
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(
                    "deletion job %s: skipped error record, lease no longer held", job_id
                )
                return
            raise

    @staticmethod
    def _lease_error_or_reraise(error: ClientError, job_id: str) -> Exception:
        """Map a failed lease-guard condition to DeletionLeaseLostError; pass others through."""
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return DeletionLeaseLostError(job_id)
        return error

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def check_table(self, table_name: str) -> None:
        await self._resource.meta.client.describe_table(TableName=table_name)

    # ------------------------------------------------------------------
    # Table initialisation
    # ------------------------------------------------------------------

    async def initialize_conversations_table(self) -> None:
        created = await create_table_if_absent(
            self._resource.meta.client,
            self.conversations_table,
            {
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "conversation_id", "KeyType": "RANGE"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "user_id", "AttributeType": "S"},
                    {"AttributeName": "conversation_id", "AttributeType": "S"},
                ],
                "ProvisionedThroughput": DYNAMODB_PROVISIONED_THROUGHPUT,
            },
        )
        if created:
            await wait_for_table_active(self._resource.meta.client, self.conversations_table)
        await self._enable_ttl(self.conversations_table, "ttl")

    async def initialize_messages_table(self) -> None:
        created = await create_table_if_absent(
            self._resource.meta.client,
            self.messages_table,
            {
                "KeySchema": [
                    {"AttributeName": "conversation_id", "KeyType": "HASH"},
                    {"AttributeName": "message_id", "KeyType": "RANGE"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "conversation_id", "AttributeType": "S"},
                    {"AttributeName": "message_id", "AttributeType": "S"},
                ],
                "ProvisionedThroughput": DYNAMODB_PROVISIONED_THROUGHPUT,
            },
        )
        if created:
            await wait_for_table_active(self._resource.meta.client, self.messages_table)
        await self._enable_ttl(self.messages_table, "ttl")

    async def initialize_deletion_jobs_table(self) -> None:
        created = await create_table_if_absent(
            self._resource.meta.client,
            self.deletion_jobs_table,
            {
                "KeySchema": [
                    {"AttributeName": "job_id", "KeyType": "HASH"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "job_id", "AttributeType": "S"},
                    {"AttributeName": "status", "AttributeType": "S"},
                    {"AttributeName": "created_at", "AttributeType": "S"},
                ],
                "ProvisionedThroughput": DYNAMODB_PROVISIONED_THROUGHPUT,
                "GlobalSecondaryIndexes": [
                    {
                        "IndexName": DELETION_JOB_STATUS_INDEX,
                        "KeySchema": [
                            {"AttributeName": "status", "KeyType": "HASH"},
                            {"AttributeName": "created_at", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                        "ProvisionedThroughput": DYNAMODB_PROVISIONED_THROUGHPUT,
                    },
                ],
            },
        )
        if created:
            await wait_for_table_active(self._resource.meta.client, self.deletion_jobs_table)
        await self._enable_ttl(self.deletion_jobs_table, "ttl")

    async def ensure_tables(self) -> None:
        await self.initialize_conversations_table()
        await self.initialize_messages_table()
        await self.initialize_deletion_jobs_table()


@lru_cache(maxsize=1)
def get_conversations_dynamodb() -> ConversationsDynamoDB:
    return ConversationsDynamoDB()
