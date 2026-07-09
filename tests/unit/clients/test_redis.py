from unittest.mock import MagicMock, patch

import pytest

from ai_assistant.clients.redis import RedisClient, build_redis_client

# ------------------------------------------------------------------
# build_redis_client
# ------------------------------------------------------------------


class TestBuildRedisClient:
    @patch("ai_assistant.clients.redis.Redis")
    def test_uses_settings(self, mock_redis):
        build_redis_client(host="redis.local", port=6380, db=2)

        mock_redis.assert_called_once_with(
            host="redis.local",
            port=6380,
            db=2,
            decode_responses=True,
        )


# ------------------------------------------------------------------
# RedisClient
# ------------------------------------------------------------------


class TestRedisClient:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.connection = MagicMock()
        self.client = RedisClient(self.connection)

    def test_get_returns_value(self):
        self.connection.get.return_value = "cached-value"

        result = self.client.get("cache-key")

        assert result == "cached-value"
        self.connection.get.assert_called_once_with("cache-key")

    def test_get_returns_none_when_key_missing(self):
        self.connection.get.return_value = None

        result = self.client.get("missing-key")

        assert result is None
        self.connection.get.assert_called_once_with("missing-key")

    def test_set_stores_value(self):
        self.connection.set.return_value = True

        result = self.client.set("cache-key", "cached-value")

        assert result is True
        self.connection.set.assert_called_once_with("cache-key", "cached-value", ex=None)

    def test_set_stores_value_with_ttl(self):
        self.connection.set.return_value = True

        result = self.client.set("cache-key", "cached-value", expiration_seconds=60)

        assert result is True
        self.connection.set.assert_called_once_with("cache-key", "cached-value", ex=60)
