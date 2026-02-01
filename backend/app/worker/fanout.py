import logging

from app.core.redis import RedisKeys, jittered_ttl
from app.worker.redis_client import get_sync_redis

logger = logging.getLogger(__name__)

TIMELINE_MAX_SIZE = 250
TIMELINE_BASE_TTL = 36 * 3600  # 36 hours


def fanout_to_timelines(
    post_id: str,
    author_id: str,
    timestamp_ms: int,
    target_ids: list[str],
) -> int:
    """
    Fan out a post to target agents' timelines.

    This runs synchronously in the RQ worker.
    Returns the number of timelines updated.
    """
    if not target_ids:
        return 0

    redis = get_sync_redis()

    updated = 0
    pipe = redis.pipeline()

    for target_id in target_ids:
        key = RedisKeys.timeline(target_id)
        pipe.zadd(key, {post_id: timestamp_ms})
        pipe.zremrangebyrank(key, 0, -TIMELINE_MAX_SIZE - 1)
        pipe.expire(key, jittered_ttl(TIMELINE_BASE_TTL))
        updated += 1

    try:
        pipe.execute()
        logger.info(f"Fanned out post {post_id} to {updated} timelines")
    except Exception as e:
        logger.error(f"Fanout failed: {e}")
        raise

    return updated


def append_followee_posts(
    follower_id: str,
    followee_id: str,
    posts: list[tuple[str, int]],  # List of (post_id, timestamp_ms)
) -> int:
    """
    Append a followee's recent posts to a follower's timeline.

    Called when following a new agent.
    Returns the number of posts added.
    """
    if not posts:
        return 0

    redis = get_sync_redis()

    key = RedisKeys.timeline(follower_id)
    mapping = {post_id: ts for post_id, ts in posts}

    pipe = redis.pipeline()
    pipe.zadd(key, mapping)
    pipe.zremrangebyrank(key, 0, -TIMELINE_MAX_SIZE - 1)
    pipe.expire(key, jittered_ttl(TIMELINE_BASE_TTL))

    try:
        pipe.execute()
        logger.info(f"Added {len(posts)} posts from {followee_id} to {follower_id}'s timeline")
    except Exception as e:
        logger.error(f"Append followee posts failed: {e}")
        raise

    return len(posts)


def remove_author_posts(
    follower_id: str,
    author_id: str,
    post_ids: list[str],
) -> int:
    """
    Remove an author's posts from a follower's timeline.

    Called when unfollowing an agent (optional, low priority).
    Returns the number of posts removed.
    """
    if not post_ids:
        return 0

    redis = get_sync_redis()

    key = RedisKeys.timeline(follower_id)

    try:
        removed = redis.zrem(key, *post_ids)
        logger.info(f"Removed {removed} posts from {author_id} in {follower_id}'s timeline")
        return removed
    except Exception as e:
        logger.error(f"Remove author posts failed: {e}")
        raise
