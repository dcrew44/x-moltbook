import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Agent, Follow
from app.schemas.agent import AgentProfile

logger = logging.getLogger(__name__)


class FollowService:
    """Service for follow operations."""

    async def follow(
        self,
        db: AsyncSession,
        follower: Agent,
        followed_handle: str,
    ) -> None:
        """Follow an agent by handle."""
        # Get target agent
        result = await db.execute(
            select(Agent).where(Agent.handle == followed_handle, Agent.is_active == True)
        )
        followed = result.scalar_one_or_none()

        if not followed:
            raise NotFoundError(
                message="Agent not found",
                code="AGENT_NOT_FOUND",
            )

        # Can't follow yourself
        if follower.id == followed.id:
            raise ValidationError(
                message="Cannot follow yourself",
                code="SELF_FOLLOW",
            )

        # Check if already following
        result = await db.execute(
            select(Follow).where(
                and_(
                    Follow.follower_id == follower.id,
                    Follow.followed_id == followed.id,
                )
            )
        )
        if result.scalar_one_or_none():
            raise ConflictError(
                message="Already following this agent",
                code="ALREADY_FOLLOWING",
            )

        # Create follow relationship
        follow = Follow(follower_id=follower.id, followed_id=followed.id)
        db.add(follow)

        # Update counters
        follower.following_count += 1
        followed.follower_count += 1

        await db.flush()
        logger.info(f"Agent {follower.handle} followed {followed.handle}")

    async def unfollow(
        self,
        db: AsyncSession,
        follower: Agent,
        followed_handle: str,
    ) -> None:
        """Unfollow an agent by handle."""
        # Get target agent
        result = await db.execute(
            select(Agent).where(Agent.handle == followed_handle, Agent.is_active == True)
        )
        followed = result.scalar_one_or_none()

        if not followed:
            raise NotFoundError(
                message="Agent not found",
                code="AGENT_NOT_FOUND",
            )

        # Find the follow relationship
        result = await db.execute(
            select(Follow).where(
                and_(
                    Follow.follower_id == follower.id,
                    Follow.followed_id == followed.id,
                )
            )
        )
        follow = result.scalar_one_or_none()

        if not follow:
            raise NotFoundError(
                message="Not following this agent",
                code="NOT_FOLLOWING",
            )

        # Update counters
        if follower.following_count > 0:
            follower.following_count -= 1
        if followed.follower_count > 0:
            followed.follower_count -= 1

        await db.delete(follow)

        logger.info(f"Agent {follower.handle} unfollowed {followed.handle}")

    async def get_followers(
        self,
        db: AsyncSession,
        handle: str,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[AgentProfile], Optional[str], bool]:
        """Get followers of an agent."""
        # Get target agent
        result = await db.execute(
            select(Agent).where(Agent.handle == handle, Agent.is_active == True)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise NotFoundError(
                message="Agent not found",
                code="AGENT_NOT_FOUND",
            )

        query = (
            select(Follow)
            .options(selectinload(Follow.follower))
            .where(Follow.followed_id == agent.id)
            .order_by(Follow.created_at.desc())
        )

        if cursor:
            cursor_time = datetime.fromisoformat(cursor)
            query = query.where(Follow.created_at < cursor_time)

        query = query.limit(limit + 1)
        result = await db.execute(query)
        follows = list(result.scalars().all())

        has_more = len(follows) > limit
        if has_more:
            follows = follows[:limit]

        next_cursor = None
        if has_more and follows:
            next_cursor = follows[-1].created_at.isoformat()

        agents = [self._agent_to_profile(f.follower) for f in follows]
        return agents, next_cursor, has_more

    async def get_following(
        self,
        db: AsyncSession,
        handle: str,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[AgentProfile], Optional[str], bool]:
        """Get agents that this agent follows."""
        # Get target agent
        result = await db.execute(
            select(Agent).where(Agent.handle == handle, Agent.is_active == True)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise NotFoundError(
                message="Agent not found",
                code="AGENT_NOT_FOUND",
            )

        query = (
            select(Follow)
            .options(selectinload(Follow.followed))
            .where(Follow.follower_id == agent.id)
            .order_by(Follow.created_at.desc())
        )

        if cursor:
            cursor_time = datetime.fromisoformat(cursor)
            query = query.where(Follow.created_at < cursor_time)

        query = query.limit(limit + 1)
        result = await db.execute(query)
        follows = list(result.scalars().all())

        has_more = len(follows) > limit
        if has_more:
            follows = follows[:limit]

        next_cursor = None
        if has_more and follows:
            next_cursor = follows[-1].created_at.isoformat()

        agents = [self._agent_to_profile(f.followed) for f in follows]
        return agents, next_cursor, has_more

    async def get_follower_ids(
        self,
        db: AsyncSession,
        agent_id: UUID,
    ) -> list[UUID]:
        """Get all follower IDs for an agent."""
        result = await db.execute(
            select(Follow.follower_id).where(Follow.followed_id == agent_id)
        )
        return [row[0] for row in result.all()]

    def _agent_to_profile(self, agent: Agent) -> AgentProfile:
        return AgentProfile(
            id=agent.id,
            handle=agent.handle,
            display_name=agent.display_name,
            bio=agent.bio,
            avatar_url=agent.avatar_url,
            moltbook_verified=agent.moltbook_verified,
            follower_count=agent.follower_count,
            following_count=agent.following_count,
            post_count=agent.post_count,
            created_at=agent.created_at,
        )


follow_service = FollowService()
