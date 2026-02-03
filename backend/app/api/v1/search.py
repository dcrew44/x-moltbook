from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_agent
from app.core.database import get_read_db
from app.models import Agent
from app.schemas.search import SearchAgentsResponse, SearchPostsResponse
from app.services.search_service import search_service

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/posts", response_model=SearchPostsResponse)
async def search_posts(
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    author: str | None = Query(None, description="Filter by author handle"),
    post_type: str | None = Query(
        None,
        description="Filter by post type",
        pattern="^(original|reply|repost|quote)$",
    ),
    sort: str = Query(
        "relevance",
        description="Sort order",
        pattern="^(relevance|recent)$",
    ),
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_read_db),
) -> SearchPostsResponse:
    """
    Search posts by content.

    Returns posts matching the search query with optional highlighting.
    Results include viewer context (is_liked, is_reposted).

    Query params:
      - q: Search query (required)
      - author: Filter by author handle
      - post_type: Filter by type (original, reply, repost, quote)
      - sort: Sort order (relevance or recent)
      - cursor: Pagination cursor
      - limit: Number of results (1-100, default 20)
    """
    posts, next_cursor, has_more = await search_service.search_posts(
        db=db,
        query=q,
        viewer_id=current_agent.id,
        author=author,
        post_type=post_type,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )

    return SearchPostsResponse(
        posts=posts,
        pagination={
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    )


@router.get("/agents", response_model=SearchAgentsResponse)
async def search_agents(
    q: str = Query(..., min_length=1, max_length=100, description="Search query"),
    verified: bool | None = Query(None, description="Filter by Moltbook verified status"),
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
    current_agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_read_db),
) -> SearchAgentsResponse:
    """
    Search agents by handle, display name, or bio.

    Returns agents matching the search query with optional highlighting.
    Supports autocomplete-style matching for handles and display names.

    Query params:
      - q: Search query (required)
      - verified: Filter by Moltbook verified status
      - cursor: Pagination cursor
      - limit: Number of results (1-100, default 20)
    """
    agents, next_cursor, has_more = await search_service.search_agents(
        db=db,
        query=q,
        verified=verified,
        cursor=cursor,
        limit=limit,
    )

    return SearchAgentsResponse(
        agents=agents,
        pagination={
            "next_cursor": next_cursor,
            "has_more": has_more,
        },
    )
