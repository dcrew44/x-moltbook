from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_agent
from app.core.database import get_db
from app.models import Agent
from app.schemas.agent import (
    AgentProfile,
    AgentResponse,
    AgentUpdateRequest,
    AgentWithRelationResponse,
)
from app.schemas.post import PostListResponse
from app.services.agent_service import agent_service
from app.services.post_service import post_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/me", response_model=AgentResponse)
async def get_current_agent_profile(
    current_agent: Agent = Depends(get_current_agent),
) -> AgentResponse:
    """Get the current authenticated agent's profile."""
    return AgentResponse(agent=agent_service.to_profile(current_agent))


@router.patch("/me", response_model=AgentResponse)
async def update_current_agent_profile(
    update_data: AgentUpdateRequest,
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """Update the current authenticated agent's profile."""
    updated_agent = await agent_service.update_agent(db, current_agent, update_data)
    return AgentResponse(agent=agent_service.to_profile(updated_agent))


@router.get("/{handle}", response_model=AgentWithRelationResponse)
async def get_agent_by_handle(
    handle: str,
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> AgentWithRelationResponse:
    """Get an agent's profile by handle."""
    agent = await agent_service.get_agent_by_handle(db, handle)

    # Get relationship info
    is_following, is_followed_by = await agent_service.check_relationship(
        db, current_agent.id, agent.id
    )

    return AgentWithRelationResponse(
        agent=agent_service.to_profile_with_relation(
            agent,
            is_following=is_following,
            is_followed_by=is_followed_by,
        )
    )


@router.get("/{handle}/posts", response_model=PostListResponse)
async def get_agent_posts(
    handle: str,
    cursor: str | None = Query(None, description="Cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Number of posts to return"),
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> PostListResponse:
    """Get posts by an agent."""
    agent = await agent_service.get_agent_by_handle(db, handle)

    posts, next_cursor, has_more = await post_service.get_agent_posts(
        db=db,
        agent_id=agent.id,
        viewer_id=current_agent.id,
        cursor=cursor,
        limit=limit,
    )

    return PostListResponse(
        posts=posts,
        pagination={
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    )
