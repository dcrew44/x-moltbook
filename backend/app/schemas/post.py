from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.post import PostType


class PostAuthor(BaseModel):
    """Embedded author info in post responses."""

    id: UUID
    handle: str
    display_name: str
    avatar_url: Optional[str] = None
    moltbook_verified: bool = False


class PostData(BaseModel):
    """Post data in API responses."""

    id: UUID
    author: PostAuthor
    content: Optional[str] = None
    post_type: PostType
    reply_to_id: Optional[UUID] = None
    repost_of_id: Optional[UUID] = None
    quote_of_id: Optional[UUID] = None
    thread_root_id: Optional[UUID] = None
    like_count: int = 0
    reply_count: int = 0
    repost_count: int = 0
    quote_count: int = 0
    created_at: datetime
    # Viewer context
    is_liked: bool = False
    is_reposted: bool = False
    # Embedded referenced posts
    reply_to: Optional["PostData"] = None
    repost_of: Optional["PostData"] = None
    quote_of: Optional["PostData"] = None


class CreatePostRequest(BaseModel):
    """Request to create a post."""

    content: Optional[str] = Field(None, max_length=500)
    post_type: PostType = PostType.ORIGINAL
    reply_to_id: Optional[UUID] = None
    repost_of_id: Optional[UUID] = None
    quote_of_id: Optional[UUID] = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: Optional[str], info) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
        return v


class PostResponse(BaseModel):
    """Response containing a single post."""

    success: bool = True
    post: PostData


class PostListResponse(BaseModel):
    """Response containing a list of posts."""

    success: bool = True
    posts: list[PostData]
    pagination: dict[str, Any]


# Update forward references
PostData.model_rebuild()
