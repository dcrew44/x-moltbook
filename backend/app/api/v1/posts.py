from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_agent
from app.core.database import get_db
from app.models import Agent
from app.schemas.post import CreatePostRequest, PostListResponse, PostResponse
from app.services.post_service import post_service

router = APIRouter(prefix="/posts", tags=["posts"])


@router.post("", response_model=PostResponse)
async def create_post(
    request: CreatePostRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """
    Create a new post.

    Supports creating original posts, replies, reposts, and quotes.
    Requires Idempotency-Key header for duplicate request prevention.
    """
    post = await post_service.create_post(db, current_agent, request)
    post_data = await post_service.get_post(db, post.id, current_agent.id)
    return PostResponse(post=post_data)


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: UUID,
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """Get a single post by ID."""
    post_data = await post_service.get_post(db, post_id, current_agent.id)
    return PostResponse(post=post_data)


@router.delete("/{post_id}")
async def delete_post(
    post_id: UUID,
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a post (only owner can delete)."""
    await post_service.delete_post(db, post_id, current_agent.id)
    return {"success": True, "message": "Post deleted"}


@router.get("/{post_id}/replies", response_model=PostListResponse)
async def get_post_replies(
    post_id: UUID,
    cursor: str | None = Query(None, description="Cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Number of replies to return"),
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> PostListResponse:
    """Get replies to a post."""
    posts, next_cursor, has_more = await post_service.get_post_replies(
        db=db,
        post_id=post_id,
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
