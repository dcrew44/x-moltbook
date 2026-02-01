import logging
import random
from typing import Optional, Union

import redis.asyncio as redis
from redis.asyncio.cluster import RedisCluster

from app.config import get_settings

logger = logging.getLogger(__name__)

AsyncRedisClient = Union[redis.Redis, RedisCluster]


class RedisManager:
    """Manages Redis connections with support for cluster mode."""

    def __init__(self):
        self._client: Optional[AsyncRedisClient] = None
        self._settings = get_settings()

    def _parse_cluster_nodes(self) -> list[dict]:
        """Parse cluster nodes from config into startup_nodes format."""
        nodes = []
        for node in self._settings.redis_cluster_nodes:
            if ":" in node:
                host, port = node.rsplit(":", 1)
                nodes.append({"host": host, "port": int(port)})
            else:
                nodes.append({"host": node, "port": 6379})
        return nodes

    async def get_client(self) -> AsyncRedisClient:
        """Get Redis client (cluster or standalone based on config)."""
        if self._client is None:
            if self._settings.redis_cluster_enabled and self._settings.redis_cluster_nodes:
                startup_nodes = self._parse_cluster_nodes()
                logger.info(f"Connecting to Redis Cluster with {len(startup_nodes)} nodes")
                self._client = RedisCluster(
                    startup_nodes=startup_nodes,
                    decode_responses=True,
                )
            else:
                logger.info("Connecting to standalone Redis")
                self._client = redis.from_url(
                    self._settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
        return self._client

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None


# Global Redis manager instance
_redis_manager: Optional[RedisManager] = None


def get_redis_manager() -> RedisManager:
    """Get the Redis manager singleton."""
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisManager()
    return _redis_manager


# Backward-compatible functions
redis_client: Optional[AsyncRedisClient] = None


async def get_redis() -> AsyncRedisClient:
    """Get Redis client singleton."""
    global redis_client
    if redis_client is None:
        redis_client = await get_redis_manager().get_client()
    return redis_client


async def close_redis() -> None:
    """Close Redis connection."""
    global redis_client
    await get_redis_manager().close()
    redis_client = None


class RedisKeys:
    """Redis key patterns."""

    @staticmethod
    def timeline(agent_id: str) -> str:
        return f"timeline:{agent_id}"

    @staticmethod
    def post_rate(agent_id: str) -> str:
        return f"post_rate:{agent_id}"

    @staticmethod
    def active(agent_id: str) -> str:
        return f"active:{agent_id}"

    @staticmethod
    def rate_limit_request(agent_id: str) -> str:
        return f"rl:req:{agent_id}"

    @staticmethod
    def rate_limit_post(agent_id: str) -> str:
        return f"rl:post:{agent_id}"

    @staticmethod
    def rate_limit_post_day(agent_id: str) -> str:
        return f"rl:post:day:{agent_id}"

    @staticmethod
    def rate_limit_like(agent_id: str) -> str:
        return f"rl:like:{agent_id}"

    @staticmethod
    def rate_limit_follow(agent_id: str) -> str:
        return f"rl:follow:{agent_id}"

    @staticmethod
    def rate_limit_public(ip: str) -> str:
        return f"rl:pub:{ip}"

    @staticmethod
    def post_cache(post_id: str) -> str:
        return f"post:{post_id}"


def jittered_ttl(base_ttl: int, jitter_percent: float = 0.2) -> int:
    """Add random jitter to TTL to prevent synchronized expiration."""
    jitter_range = int(base_ttl * jitter_percent)
    return base_ttl + random.randint(-jitter_range, jitter_range)
