import asyncio
import sys
from functools import lru_cache
from typing import Any

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ai_assistant.constants import DYNAMODB_PROVISIONED_THROUGHPUT
from config import AWS_DEFAULT_REGION, DYNAMODB_ENDPOINT_URL, DYNAMODB_STATUS_TABLE_NAME

_DYNAMODB_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "standard"})

_resource = None
_resource_cm = None
_lock = asyncio.Lock()


async def open_dynamodb_resource() -> None:
    """Open the shared aioboto3 DynamoDB resource. Call once at application startup."""
    global _resource, _resource_cm
    async with _lock:
        if _resource is not None:
            raise RuntimeError(
                "DynamoDB resource is already open — call close_dynamodb_resource() first."
            )
        session = aioboto3.Session()
        cm = session.resource(
            "dynamodb",
            endpoint_url=DYNAMODB_ENDPOINT_URL,
            region_name=AWS_DEFAULT_REGION,
            config=_DYNAMODB_RETRY_CONFIG,
        )
        # Assign globals only after __aenter__ succeeds so close_dynamodb_resource()
        # never sees a half-initialised context manager.
        # If __aenter__ raises, call __aexit__ with the exception so the CM can
        # clean up any resources it may have allocated before the error.
        try:
            resource = await cm.__aenter__()
        except BaseException:
            await cm.__aexit__(*sys.exc_info())
            raise
        _resource_cm = cm
        _resource = resource


async def close_dynamodb_resource() -> None:
    """Close the shared aioboto3 DynamoDB resource. Call once at application shutdown."""
    global _resource, _resource_cm
    async with _lock:
        cm, _resource_cm = _resource_cm, None
        _resource = None
        # Clear singleton caches *inside the lock* so a concurrent
        # open_dynamodb_resource() call cannot race between the close and the
        # cache clear, leaving stale client instances pointing at a new resource.
        # Deferred import avoids a circular import with conversations_dynamodb.
        # Use try/finally so cache clears always run even if __aexit__ raises.
        try:
            if cm is not None:
                await cm.__aexit__(None, None, None)
        finally:
            get_dynamodb_client.cache_clear()
            from ai_assistant.clients.conversations_dynamodb import (
                get_conversations_dynamodb,  # noqa: PLC0415
            )

            get_conversations_dynamodb.cache_clear()


def get_dynamodb_resource() -> Any | None:
    """Return the shared aioboto3 DynamoDB resource (opened at startup), or None."""
    return _resource


async def table_exists(client: Any, table_name: str) -> bool:
    try:
        await client.describe_table(TableName=table_name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


async def create_table_if_absent(
    client: Any,
    table_name: str,
    schema: dict[str, Any],
) -> bool:
    """Create the table if it does not exist.

    Returns True if creation was attempted (table was absent — it may still be in
    CREATING state), False if the table already existed and is presumed ACTIVE.
    Callers should call wait_for_table_active only when this returns True.

    A concurrent creator (another booting instance) is tolerated by catching
    ResourceInUseException via its error code; the table still gets created exactly once.
    Using the error code rather than client.exceptions.ResourceInUseException avoids
    an AttributeError when the attribute is absent on mocks or non-DynamoDB clients.
    """
    if await table_exists(client, table_name):
        return False
    try:
        await client.create_table(TableName=table_name, **schema)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise
    return True


async def wait_for_table_active(client: Any, table_name: str) -> None:
    waiter = client.get_waiter("table_exists")
    await waiter.wait(TableName=table_name)


class DynamoDB:
    def __init__(
        self,
        table_name: str = DYNAMODB_STATUS_TABLE_NAME,
    ) -> None:
        self.table_name = table_name

    @property
    def _resource(self) -> Any:
        resource = get_dynamodb_resource()
        if resource is None:
            raise RuntimeError(
                "DynamoDB resource is not initialized — "
                "ensure open_dynamodb_resource() has been called before using this client."
            )
        return resource

    @property
    def status_table(self) -> str:
        """Public name of the status table, used by health-check endpoints.

        Exposed as a named property so callers (e.g. health.py) can read
        a semantically meaningful attribute without knowing that the internal
        storage is ``table_name``.
        """
        return self.table_name

    async def provision_status_table(self) -> None:
        client = self._resource.meta.client
        created = await create_table_if_absent(
            client,
            self.table_name,
            {
                "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
                "AttributeDefinitions": [{"AttributeName": "pk", "AttributeType": "S"}],
                "ProvisionedThroughput": DYNAMODB_PROVISIONED_THROUGHPUT,
            },
        )
        if created:
            await wait_for_table_active(client, self.table_name)

    async def check_status_table(self) -> None:
        await self._resource.meta.client.describe_table(TableName=self.table_name)


@lru_cache(maxsize=1)
def get_dynamodb_client() -> DynamoDB:
    return DynamoDB()
