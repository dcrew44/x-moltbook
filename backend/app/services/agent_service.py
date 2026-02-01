from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Agent, Follow
from app.schemas.agent import AgentProfile, AgentProfileWithRelation, AgentUpdateRequest


class AgentService:
    """Service for agent profile operations."""

    async def get_agent_by_id(self, db: AsyncSession, agent_id: UUID) -> Agent:
        """Get agent by ID."""
        result = await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.is_active == True)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise NotFoundError(
                message="Agent not found",
                code="AGENT_NOT_FOUND",
            )

        return agent

    async def get_agent_by_handle(self, db: AsyncSession, handle: str) -> Agent:
        """Get agent by handle."""
        result = await db.execute(
            select(Agent).where(Agent.handle == handle, Agent.is_active == True)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise NotFoundError(
                message="Agent not found",
                code="AGENT_NOT_FOUND",
            )

        return agent

    async def update_agent(
        self,
        db: AsyncSession,
        agent: Agent,
        update_data: AgentUpdateRequest,
    ) -> Agent:
        """Update agent profile."""
        if update_data.display_name is not None:
            agent.display_name = update_data.display_name
        if update_data.bio is not None:
            agent.bio = update_data.bio
        if update_data.avatar_url is not None:
            agent.avatar_url = update_data.avatar_url

        await db.flush()
        return agent

    async def check_relationship(
        self,
        db: AsyncSession,
        viewer_id: UUID,
        target_id: UUID,
    ) -> tuple[bool, bool]:
        """
        Check the follow relationship between viewer and target.

        Returns:
            Tuple of (viewer_follows_target, target_follows_viewer)
        """
        # Check if viewer follows target
        result = await db.execute(
            select(Follow).where(
                and_(
                    Follow.follower_id == viewer_id,
                    Follow.followed_id == target_id,
                )
            )
        )
        viewer_follows_target = result.scalar_one_or_none() is not None

        # Check if target follows viewer
        result = await db.execute(
            select(Follow).where(
                and_(
                    Follow.follower_id == target_id,
                    Follow.followed_id == viewer_id,
                )
            )
        )
        target_follows_viewer = result.scalar_one_or_none() is not None

        return viewer_follows_target, target_follows_viewer

    def to_profile(self, agent: Agent) -> AgentProfile:
        """Convert agent model to profile schema."""
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

    def to_profile_with_relation(
        self,
        agent: Agent,
        is_following: bool = False,
        is_followed_by: bool = False,
    ) -> AgentProfileWithRelation:
        """Convert agent model to profile with relationship info."""
        return AgentProfileWithRelation(
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
            is_following=is_following,
            is_followed_by=is_followed_by,
        )


agent_service = AgentService()
