import random
from typing import Optional

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()

redis_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get Redis client singleton."""
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return redis_client


async def close_redis() -> None:
    """Close Redis connection."""
    global redis_client
    if redis_client is not None:
        await redis_client.close()
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
