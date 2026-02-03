"""Background indexing tasks for Elasticsearch."""

import logging
from datetime import datetime
from typing import Optional

from rq import get_current_job

from app.worker.elasticsearch_client import (
    get_agents_index,
    get_posts_index,
    get_sync_es,
    is_elasticsearch_enabled,
)

logger = logging.getLogger(__name__)


def index_post_task(
    post_id: str,
    author_id: str,
    author_handle: str,
    author_display_name: str,
    content: Optional[str],
    post_type: str,
    created_at: str,
    like_count: int = 0,
    reply_count: int = 0,
    repost_count: int = 0,
    quote_count: int = 0,
) -> dict:
    """
    RQ task to index a post in Elasticsearch.

    Args:
        post_id: UUID of the post
        author_id: UUID of the post author
        author_handle: Author's handle
        author_display_name: Author's display name
        content: Post content (may be None for pure reposts)
        post_type: Type of post (original, reply, repost, quote)
        created_at: ISO format timestamp
        like_count: Number of likes
        reply_count: Number of replies
        repost_count: Number of reposts
        quote_count: Number of quotes

    Returns:
        Dict with task result info
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    if not is_elasticsearch_enabled():
        logger.debug(f"[{job_id}] Elasticsearch disabled, skipping post indexing")
        return {"success": True, "skipped": True, "reason": "elasticsearch_disabled"}

    logger.info(f"[{job_id}] Indexing post {post_id}")

    try:
        es = get_sync_es()
        doc = {
            "content": content,
            "author_id": author_id,
            "author_handle": author_handle,
            "author_display_name": author_display_name,
            "post_type": post_type,
            "created_at": created_at,
            "like_count": like_count,
            "reply_count": reply_count,
            "repost_count": repost_count,
            "quote_count": quote_count,
        }

        es.index(index=get_posts_index(), id=post_id, document=doc)

        return {
            "success": True,
            "post_id": post_id,
        }
    except Exception as e:
        logger.error(f"[{job_id}] Failed to index post {post_id}: {e}")
        return {
            "success": False,
            "post_id": post_id,
            "error": str(e),
        }


def delete_post_from_index_task(post_id: str) -> dict:
    """
    RQ task to delete a post from Elasticsearch.

    Args:
        post_id: UUID of the post to delete

    Returns:
        Dict with task result info
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    if not is_elasticsearch_enabled():
        logger.debug(f"[{job_id}] Elasticsearch disabled, skipping post deletion")
        return {"success": True, "skipped": True, "reason": "elasticsearch_disabled"}

    logger.info(f"[{job_id}] Deleting post {post_id} from index")

    try:
        es = get_sync_es()
        es.delete(index=get_posts_index(), id=post_id, ignore=[404])

        return {
            "success": True,
            "post_id": post_id,
        }
    except Exception as e:
        logger.error(f"[{job_id}] Failed to delete post {post_id} from index: {e}")
        return {
            "success": False,
            "post_id": post_id,
            "error": str(e),
        }


def index_agent_task(
    agent_id: str,
    handle: str,
    display_name: str,
    bio: Optional[str],
    moltbook_verified: bool = False,
    is_active: bool = True,
    follower_count: int = 0,
    following_count: int = 0,
    post_count: int = 0,
    created_at: Optional[str] = None,
) -> dict:
    """
    RQ task to index an agent in Elasticsearch.

    Args:
        agent_id: UUID of the agent
        handle: Agent's handle
        display_name: Agent's display name
        bio: Agent's bio (may be None)
        moltbook_verified: Whether agent is Moltbook verified
        is_active: Whether agent is active
        follower_count: Number of followers
        following_count: Number of following
        post_count: Number of posts
        created_at: ISO format timestamp of account creation

    Returns:
        Dict with task result info
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    if not is_elasticsearch_enabled():
        logger.debug(f"[{job_id}] Elasticsearch disabled, skipping agent indexing")
        return {"success": True, "skipped": True, "reason": "elasticsearch_disabled"}

    logger.info(f"[{job_id}] Indexing agent {agent_id} (@{handle})")

    try:
        es = get_sync_es()
        doc = {
            "handle": handle,
            "display_name": display_name,
            "bio": bio,
            "moltbook_verified": moltbook_verified,
            "is_active": is_active,
            "follower_count": follower_count,
            "following_count": following_count,
            "post_count": post_count,
            "created_at": created_at,
        }

        es.index(index=get_agents_index(), id=agent_id, document=doc)

        return {
            "success": True,
            "agent_id": agent_id,
        }
    except Exception as e:
        logger.error(f"[{job_id}] Failed to index agent {agent_id}: {e}")
        return {
            "success": False,
            "agent_id": agent_id,
            "error": str(e),
        }


def update_agent_stats_task(
    agent_id: str,
    updates: dict,
) -> dict:
    """
    RQ task to update agent stats in Elasticsearch.

    Args:
        agent_id: UUID of the agent
        updates: Dictionary of fields to update (e.g., {"follower_count": 100})

    Returns:
        Dict with task result info
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    if not is_elasticsearch_enabled():
        logger.debug(f"[{job_id}] Elasticsearch disabled, skipping agent stats update")
        return {"success": True, "skipped": True, "reason": "elasticsearch_disabled"}

    logger.info(f"[{job_id}] Updating agent {agent_id} stats: {updates}")

    try:
        es = get_sync_es()
        es.update(
            index=get_agents_index(),
            id=agent_id,
            doc=updates,
            doc_as_upsert=False,
        )

        return {
            "success": True,
            "agent_id": agent_id,
            "updates": updates,
        }
    except Exception as e:
        logger.error(f"[{job_id}] Failed to update agent {agent_id} stats: {e}")
        return {
            "success": False,
            "agent_id": agent_id,
            "error": str(e),
        }


def update_post_stats_task(
    post_id: str,
    updates: dict,
) -> dict:
    """
    RQ task to update post stats in Elasticsearch.

    Args:
        post_id: UUID of the post
        updates: Dictionary of fields to update (e.g., {"like_count": 10})

    Returns:
        Dict with task result info
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    if not is_elasticsearch_enabled():
        logger.debug(f"[{job_id}] Elasticsearch disabled, skipping post stats update")
        return {"success": True, "skipped": True, "reason": "elasticsearch_disabled"}

    logger.info(f"[{job_id}] Updating post {post_id} stats: {updates}")

    try:
        es = get_sync_es()
        es.update(
            index=get_posts_index(),
            id=post_id,
            doc=updates,
            doc_as_upsert=False,
        )

        return {
            "success": True,
            "post_id": post_id,
            "updates": updates,
        }
    except Exception as e:
        logger.error(f"[{job_id}] Failed to update post {post_id} stats: {e}")
        return {
            "success": False,
            "post_id": post_id,
            "error": str(e),
        }
