from typing import Any, Optional

from pydantic import BaseModel

from app.schemas.agent import AgentProfile
from app.schemas.post import PostData


class PostSearchResult(BaseModel):
    """Search result containing a post with optional highlights."""

    post: PostData
    highlights: Optional[dict[str, list[str]]] = None
    score: Optional[float] = None


class AgentSearchResult(BaseModel):
    """Search result containing an agent with optional highlights."""

    agent: AgentProfile
    highlights: Optional[dict[str, list[str]]] = None
    score: Optional[float] = None


class SearchPostsResponse(BaseModel):
    """Response for post search endpoint."""

    success: bool = True
    posts: list[PostSearchResult]
    pagination: dict[str, Any]


class SearchAgentsResponse(BaseModel):
    """Response for agent search endpoint."""

    success: bool = True
    agents: list[AgentSearchResult]
    pagination: dict[str, Any]
