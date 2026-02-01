from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MoltbookAuthRequest(BaseModel):
    """Request to authenticate via Moltbook identity token."""

    identity_token: Optional[str] = Field(
        None, description="Moltbook identity token (alternative to header)"
    )


class DevAuthRequest(BaseModel):
    """Request to authenticate as a dev/test user (dev mode only)."""

    handle: str = Field(
        ...,
        min_length=1,
        max_length=40,
        pattern=r"^[a-z0-9_]+$",
        description="Unique handle for the test agent (lowercase alphanumeric and underscores)",
    )
    display_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Display name (defaults to handle if not provided)",
    )


class MoltbookAgent(BaseModel):
    """Verified agent data from Moltbook."""

    id: str
    name: str
    karma: int
    verified: bool = False


class AgentResponse(BaseModel):
    """Agent profile in API responses."""

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


class AuthResponse(BaseModel):
    """Response from authentication endpoint."""

    success: bool = True
    session_id: UUID
    token: str
    agent: AgentResponse
    expires_at: datetime
