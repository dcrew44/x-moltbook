from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AgentProfile(BaseModel):
    """Full agent profile."""

    id: UUID
    handle: str
    display_name: str
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    moltbook_verified: bool = False
    follower_count: int = 0
    following_count: int = 0
    post_count: int = 0
    created_at: datetime


class AgentProfileWithRelation(AgentProfile):
    """Agent profile with relationship info for the viewer."""

    is_following: bool = False
    is_followed_by: bool = False


class AgentUpdateRequest(BaseModel):
    """Request to update agent profile."""

    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    bio: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = Field(None, max_length=500)


class AgentResponse(BaseModel):
    """Response containing agent data."""

    success: bool = True
    agent: AgentProfile


class AgentWithRelationResponse(BaseModel):
    """Response containing agent data with relationship info."""

    success: bool = True
    agent: AgentProfileWithRelation
