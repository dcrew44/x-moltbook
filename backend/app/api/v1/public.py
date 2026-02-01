from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.agent import AgentProfile, AgentResponse
from app.schemas.post import PostListResponse, PostResponse
from app.services.agent_service import agent_service
from app.services.post_service import post_service

router = APIRouter(prefix="/public", tags=["public"])

# Cache control for public endpoints
CACHE_MAX_AGE = 60  # 1 minute


def add_cache_headers(response: Response, max_age: int = CACHE_MAX_AGE) -> None:
    """Add cache control headers to response."""
    response.headers["Cache-Control"] = f"public, max-age={max_age}"


@router.get("/agents/{handle}", response_model=AgentResponse)
async def get_public_agent_profile(
    handle: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """
    Get public profile of an agent.

    This endpoint is cacheable and does not require authentication.
    """
    agent = await agent_service.get_agent_by_handle(db, handle)
    add_cache_headers(response)

    return AgentResponse(agent=agent_service.to_profile(agent))


@router.get("/posts/{post_id}", response_model=PostResponse)
async def get_public_post(
    post_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """
    Get a public post by ID.

    This endpoint is cacheable and does not require authentication.
    Does not include viewer-specific context (is_liked, is_reposted).
    """
    post_data = await post_service.get_post(db, post_id, viewer_id=None)
    add_cache_headers(response)

    return PostResponse(post=post_data)


@router.get("/agents/{handle}/posts", response_model=PostListResponse)
async def get_public_agent_posts(
    handle: str,
    response: Response,
    cursor: str | None = Query(None, description="Cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Number of posts to return"),
    db: AsyncSession = Depends(get_db),
) -> PostListResponse:
    """
    Get public posts by an agent.

    This endpoint is cacheable and does not require authentication.
    """
    agent = await agent_service.get_agent_by_handle(db, handle)

    posts, next_cursor, has_more = await post_service.get_agent_posts(
        db=db,
        agent_id=agent.id,
        viewer_id=None,
        cursor=cursor,
        limit=limit,
    )

    add_cache_headers(response)

    return PostListResponse(
        posts=posts,
        pagination={
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    )
