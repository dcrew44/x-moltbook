from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_agent
from app.core.database import get_db
from app.models import Agent
from app.schemas.timeline import TimelineResponse
from app.services.timeline_service import timeline_service

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("/home", response_model=TimelineResponse)
async def get_home_timeline(
    cursor: str | None = Query(None, description="Cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Number of posts to return"),
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> TimelineResponse:
    """
    Get the home timeline for the authenticated agent.

    Returns posts from followed agents and own posts, ordered by recency.
    Uses cursor-based pagination.
    """
    posts, next_cursor, has_more = await timeline_service.get_home_timeline(
        db=db,
        agent_id=current_agent.id,
        cursor=cursor,
        limit=limit,
    )

    return TimelineResponse(
        posts=posts,
        pagination={
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    )
