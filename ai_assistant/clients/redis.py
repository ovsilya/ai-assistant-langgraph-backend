from __future__ import annotations

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from ai_assistant.utils import retry_if_error
from config import REDIS_DB, REDIS_HOST, REDIS_PORT

_REDIS_RETRY_EXCEPTIONS = (RedisConnectionError, RedisTimeoutError)


class RedisClient:
    def __init__(self, connection: Redis[str]) -> None:
        self.connection = connection

    @retry_if_error(number_of_tries=3, delay=0.5, exceptions=_REDIS_RETRY_EXCEPTIONS)
    def get(self, key: str) -> str | None:
        return self.connection.get(key)

    @retry_if_error(number_of_tries=3, delay=0.5, exceptions=_REDIS_RETRY_EXCEPTIONS)
    def set(
        self,
        key: str,
        value: str,
        expiration_seconds: int | None = None,
    ) -> bool:
        return bool(self.connection.set(key, value, ex=expiration_seconds))


def build_redis_client(
    host: str = REDIS_HOST,
    port: int = REDIS_PORT,
    db: int = REDIS_DB,
) -> Redis[str]:
    return Redis(
        host=host,
        port=port,
        db=db,
        decode_responses=True,
    )
