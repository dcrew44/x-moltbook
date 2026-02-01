from typing import Any

from pydantic import BaseModel

from app.schemas.agent import AgentProfile


class FollowResponse(BaseModel):
    """Response for follow/unfollow operations."""

    success: bool = True
    message: str


class FollowerListResponse(BaseModel):
    """Response containing list of followers/following."""

    success: bool = True
    agents: list[AgentProfile]
    pagination: dict[str, Any]
