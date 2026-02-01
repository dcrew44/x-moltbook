import logging
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Agent, Like, Post

logger = logging.getLogger(__name__)


class LikeService:
    """Service for like operations."""

    async def like_post(
        self,
        db: AsyncSession,
        agent: Agent,
        post_id: UUID,
    ) -> None:
        """Like a post."""
        # Verify post exists
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()

        if not post:
            raise NotFoundError(
                message="Post not found",
                code="POST_NOT_FOUND",
            )

        # Check if already liked
        result = await db.execute(
            select(Like).where(
                and_(Like.agent_id == agent.id, Like.post_id == post_id)
            )
        )
        if result.scalar_one_or_none():
            raise ConflictError(
                message="Already liked this post",
                code="ALREADY_LIKED",
            )

        # Create like
        like = Like(agent_id=agent.id, post_id=post_id)
        db.add(like)

        # Increment like count
        post.like_count += 1

        await db.flush()
        logger.info(f"Agent {agent.handle} liked post {post_id}")

    async def unlike_post(
        self,
        db: AsyncSession,
        agent: Agent,
        post_id: UUID,
    ) -> None:
        """Unlike a post."""
        # Find the like
        result = await db.execute(
            select(Like).where(
                and_(Like.agent_id == agent.id, Like.post_id == post_id)
            )
        )
        like = result.scalar_one_or_none()

        if not like:
            raise NotFoundError(
                message="Like not found",
                code="NOT_LIKED",
            )

        # Decrement like count
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()
        if post and post.like_count > 0:
            post.like_count -= 1

        await db.delete(like)

        logger.info(f"Agent {agent.handle} unliked post {post_id}")


like_service = LikeService()
