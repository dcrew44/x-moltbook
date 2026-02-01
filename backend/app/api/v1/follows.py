from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_agent
from app.core.database import get_db
from app.models import Agent
from app.schemas.follow import FollowerListResponse, FollowResponse
from app.services.follow_service import follow_service

router = APIRouter(prefix="/agents", tags=["follows"])


@router.post("/{handle}/follow", response_model=FollowResponse)
async def follow_agent(
    handle: str,
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> FollowResponse:
    """Follow an agent."""
    await follow_service.follow(db, current_agent, handle)
    return FollowResponse(message=f"Now following @{handle}")


@router.delete("/{handle}/follow", response_model=FollowResponse)
async def unfollow_agent(
    handle: str,
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> FollowResponse:
    """Unfollow an agent."""
    await follow_service.unfollow(db, current_agent, handle)
    return FollowResponse(message=f"Unfollowed @{handle}")


@router.get("/{handle}/followers", response_model=FollowerListResponse)
async def get_followers(
    handle: str,
    cursor: str | None = Query(None, description="Cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> FollowerListResponse:
    """Get followers of an agent."""
    agents, next_cursor, has_more = await follow_service.get_followers(
        db=db,
        handle=handle,
        cursor=cursor,
        limit=limit,
    )

    return FollowerListResponse(
        agents=agents,
        pagination={
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    )


@router.get("/{handle}/following", response_model=FollowerListResponse)
async def get_following(
    handle: str,
    cursor: str | None = Query(None, description="Cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> FollowerListResponse:
    """Get agents that this agent follows."""
    agents, next_cursor, has_more = await follow_service.get_following(
        db=db,
        handle=handle,
        cursor=cursor,
        limit=limit,
    )

    return FollowerListResponse(
        agents=agents,
        pagination={
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    )
