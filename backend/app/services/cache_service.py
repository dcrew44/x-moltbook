import json
import logging
from typing import Optional
from uuid import UUID

from app.core.redis import RedisKeys, get_redis, jittered_ttl

logger = logging.getLogger(__name__)

TIMELINE_MAX_SIZE = 250
TIMELINE_BASE_TTL = 36 * 3600  # 36 hours


class CacheService:
    """Service for Redis caching operations."""

    async def add_to_timeline(
        self,
        agent_id: UUID,
        post_id: UUID,
        timestamp_ms: int,
    ) -> None:
        """Add a post to an agent's timeline cache."""
        try:
            redis = await get_redis()
            key = RedisKeys.timeline(str(agent_id))

            pipe = redis.pipeline()
            # Add post with timestamp score
            pipe.zadd(key, {str(post_id): timestamp_ms})
            # Trim to max size (keep highest scores = newest)
            pipe.zremrangebyrank(key, 0, -TIMELINE_MAX_SIZE - 1)
            # Set TTL with jitter
            pipe.expire(key, jittered_ttl(TIMELINE_BASE_TTL))
            await pipe.execute()

        except Exception as e:
            logger.warning(f"Failed to add to timeline cache: {e}")

    async def add_posts_to_timeline(
        self,
        agent_id: UUID,
        posts: list[tuple[UUID, int]],  # List of (post_id, timestamp_ms)
    ) -> None:
        """Add multiple posts to an agent's timeline cache."""
        if not posts:
            return

        try:
            redis = await get_redis()
            key = RedisKeys.timeline(str(agent_id))

            mapping = {str(post_id): ts for post_id, ts in posts}

            pipe = redis.pipeline()
            pipe.zadd(key, mapping)
            pipe.zremrangebyrank(key, 0, -TIMELINE_MAX_SIZE - 1)
            pipe.expire(key, jittered_ttl(TIMELINE_BASE_TTL))
            await pipe.execute()

        except Exception as e:
            logger.warning(f"Failed to add posts to timeline cache: {e}")

    async def get_timeline(
        self,
        agent_id: UUID,
        limit: int = 20,
        max_score: Optional[int] = None,
    ) -> tuple[list[UUID], Optional[int]]:
        """
        Get timeline post IDs from cache.

        Returns:
            Tuple of (post_ids, next_cursor_score)
        """
        try:
            redis = await get_redis()
            key = RedisKeys.timeline(str(agent_id))

            # Get posts with scores
            if max_score:
                results = await redis.zrevrangebyscore(
                    key,
                    max=max_score - 1,  # Exclusive
                    min="-inf",
                    start=0,
                    num=limit + 1,
                    withscores=True,
                )
            else:
                results = await redis.zrevrange(
                    key,
                    start=0,
                    end=limit,
                    withscores=True,
                )

            if not results:
                return [], None

            post_ids = [UUID(post_id) for post_id, _ in results[:limit]]
            next_cursor = None
            if len(results) > limit:
                next_cursor = int(results[limit - 1][1])  # Score of last returned item

            return post_ids, next_cursor

        except Exception as e:
            logger.warning(f"Failed to get timeline from cache: {e}")
            return [], None

    async def remove_from_timeline(
        self,
        agent_id: UUID,
        post_ids: list[UUID],
    ) -> None:
        """Remove posts from an agent's timeline cache."""
        if not post_ids:
            return

        try:
            redis = await get_redis()
            key = RedisKeys.timeline(str(agent_id))
            await redis.zrem(key, *[str(pid) for pid in post_ids])

        except Exception as e:
            logger.warning(f"Failed to remove from timeline cache: {e}")

    async def is_agent_active(self, agent_id: UUID) -> bool:
        """Check if an agent is marked as active."""
        try:
            redis = await get_redis()
            return await redis.exists(RedisKeys.active(str(agent_id))) > 0
        except Exception:
            return False

    async def get_active_follower_ids(
        self,
        follower_ids: list[UUID],
    ) -> list[UUID]:
        """Filter follower IDs to only include active ones."""
        if not follower_ids:
            return []

        try:
            redis = await get_redis()
            pipe = redis.pipeline()
            for fid in follower_ids:
                pipe.exists(RedisKeys.active(str(fid)))
            results = await pipe.execute()

            return [fid for fid, is_active in zip(follower_ids, results) if is_active]

        except Exception as e:
            logger.warning(f"Failed to check active followers: {e}")
            return []

    async def get_post_rate(self, agent_id: UUID) -> int:
        """Get recent post rate for an agent."""
        try:
            redis = await get_redis()
            rate = await redis.get(RedisKeys.post_rate(str(agent_id)))
            return int(rate) if rate else 0
        except Exception:
            return 0

    async def increment_post_rate(self, agent_id: UUID) -> None:
        """Increment post rate counter for an agent."""
        try:
            redis = await get_redis()
            key = RedisKeys.post_rate(str(agent_id))
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, 900)  # 15 minutes
            await pipe.execute()
        except Exception as e:
            logger.warning(f"Failed to increment post rate: {e}")

    async def cache_post(
        self,
        post_id: UUID,
        post_data: dict,
        ttl: int = 300,
    ) -> None:
        """Cache post data for hot posts."""
        try:
            redis = await get_redis()
            await redis.set(
                RedisKeys.post_cache(str(post_id)),
                json.dumps(post_data),
                ex=ttl,
            )
        except Exception as e:
            logger.warning(f"Failed to cache post: {e}")

    async def get_cached_post(self, post_id: UUID) -> Optional[dict]:
        """Get cached post data."""
        try:
            redis = await get_redis()
            data = await redis.get(RedisKeys.post_cache(str(post_id)))
            return json.loads(data) if data else None
        except Exception:
            return None


cache_service = CacheService()
