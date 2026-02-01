from typing import Any

from pydantic import BaseModel

from app.schemas.post import PostData


class TimelineResponse(BaseModel):
    """Response containing timeline posts."""

    success: bool = True
    posts: list[PostData]
    pagination: dict[str, Any]
