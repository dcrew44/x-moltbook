from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_agent
from app.core.database import get_db
from app.models import Agent
from app.services.like_service import like_service

router = APIRouter(prefix="/posts", tags=["likes"])


@router.post("/{post_id}/like")
async def like_post(
    post_id: UUID,
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Like a post."""
    await like_service.like_post(db, current_agent, post_id)
    return {"success": True, "message": "Post liked"}


@router.delete("/{post_id}/like")
async def unlike_post(
    post_id: UUID,
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Unlike a post."""
    await like_service.unlike_post(db, current_agent, post_id)
    return {"success": True, "message": "Post unliked"}
