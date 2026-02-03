import logging

from rq import get_current_job

from app.worker.fanout import append_followee_posts, fanout_to_timelines, remove_author_posts

# Conditionally import indexing tasks
try:
    from app.worker.indexing import (
        delete_post_from_index_task,
        index_agent_task,
        index_post_task,
        update_agent_stats_task,
        update_post_stats_task,
    )
    ES_AVAILABLE = True
except ImportError:
    ES_AVAILABLE = False

logger = logging.getLogger(__name__)

# Re-export tasks for RQ discovery
__all__ = [
    "fanout_post_task",
    "append_followee_posts_task",
    "remove_author_posts_task",
]

if ES_AVAILABLE:
    __all__.extend([
        "index_post_task",
        "delete_post_from_index_task",
        "index_agent_task",
        "update_agent_stats_task",
        "update_post_stats_task",
    ])


def fanout_post_task(
    post_id: str,
    author_id: str,
    timestamp_ms: int,
    target_ids: list[str],
) -> dict:
    """
    RQ task to fan out a post to followers' timelines.

    Args:
        post_id: UUID of the post
        author_id: UUID of the post author
        timestamp_ms: Timestamp in milliseconds for sorting
        target_ids: List of follower UUIDs to fan out to

    Returns:
        Dict with task result info
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    logger.info(f"[{job_id}] Starting fanout for post {post_id} to {len(target_ids)} targets")

    try:
        updated = fanout_to_timelines(post_id, author_id, timestamp_ms, target_ids)
        return {
            "success": True,
            "post_id": post_id,
            "timelines_updated": updated,
        }
    except Exception as e:
        logger.error(f"[{job_id}] Fanout failed: {e}")
        return {
            "success": False,
            "post_id": post_id,
            "error": str(e),
        }


def append_followee_posts_task(
    follower_id: str,
    followee_id: str,
    posts: list[tuple[str, int]],
    followee_follower_count: int = 0,
) -> dict:
    """
    RQ task to append a followee's posts to a follower's timeline.

    Called when a new follow relationship is created.

    Args:
        follower_id: UUID of the follower
        followee_id: UUID of the agent being followed
        posts: List of (post_id, timestamp_ms) tuples
        followee_follower_count: Follower count of the followee (for celebrity check)

    Returns:
        Dict with task result info
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    logger.info(f"[{job_id}] Appending {len(posts)} posts from {followee_id} to {follower_id}")

    try:
        added = append_followee_posts(follower_id, followee_id, posts, followee_follower_count)
        return {
            "success": True,
            "follower_id": follower_id,
            "followee_id": followee_id,
            "posts_added": added,
        }
    except Exception as e:
        logger.error(f"[{job_id}] Append posts failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def remove_author_posts_task(
    follower_id: str,
    author_id: str,
    post_ids: list[str],
) -> dict:
    """
    RQ task to remove an author's posts from a follower's timeline.

    Called when an unfollow relationship is created (low priority).

    Args:
        follower_id: UUID of the follower
        author_id: UUID of the unfollowed author
        post_ids: List of post UUIDs to remove

    Returns:
        Dict with task result info
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    logger.info(f"[{job_id}] Removing {len(post_ids)} posts from {author_id} in {follower_id}'s timeline")

    try:
        removed = remove_author_posts(follower_id, author_id, post_ids)
        return {
            "success": True,
            "follower_id": follower_id,
            "author_id": author_id,
            "posts_removed": removed,
        }
    except Exception as e:
        logger.error(f"[{job_id}] Remove posts failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }
