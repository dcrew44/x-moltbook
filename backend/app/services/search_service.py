import base64
import json
import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.elasticsearch import get_es_manager
from app.models import Agent, Post
from app.schemas.agent import AgentProfile
from app.schemas.post import PostData
from app.schemas.search import AgentSearchResult, PostSearchResult
from app.services.agent_service import agent_service
from app.services.post_service import post_service

logger = logging.getLogger(__name__)


def encode_cursor(sort_values: list) -> str:
    """Encode search_after values as a cursor string."""
    return base64.urlsafe_b64encode(json.dumps(sort_values).encode()).decode()


def decode_cursor(cursor: str) -> Optional[list]:
    """Decode cursor string to search_after values."""
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        return None


class SearchService:
    """Service for search operations using Elasticsearch."""

    async def search_posts(
        self,
        db: AsyncSession,
        query: str,
        viewer_id: Optional[UUID] = None,
        author: Optional[str] = None,
        post_type: Optional[str] = None,
        sort: str = "relevance",
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[PostSearchResult], Optional[str], bool]:
        """
        Search posts by content.

        Args:
            db: Database session
            query: Search query string
            viewer_id: Optional viewer ID for is_liked/is_reposted context
            author: Optional author handle to filter by
            post_type: Optional post type filter (original, reply, repost, quote)
            sort: Sort order (relevance or recent)
            cursor: Pagination cursor (base64 encoded search_after values)
            limit: Number of results to return

        Returns:
            Tuple of (results, next_cursor, has_more)
        """
        settings = get_settings()
        if not settings.elasticsearch_enabled:
            return [], None, False

        es_manager = get_es_manager()
        es = await es_manager.get_client()

        # Build query
        must_clauses = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["content^2", "author_handle", "author_display_name"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            }
        ]

        filter_clauses = []
        if author:
            filter_clauses.append({"term": {"author_handle.keyword": author}})
        if post_type:
            filter_clauses.append({"term": {"post_type": post_type}})

        es_query = {
            "bool": {
                "must": must_clauses,
                "filter": filter_clauses if filter_clauses else None,
            }
        }

        # Remove None filter
        if es_query["bool"]["filter"] is None:
            del es_query["bool"]["filter"]

        # Build sort
        if sort == "recent":
            sort_clause = [
                {"created_at": {"order": "desc"}},
                {"_id": {"order": "desc"}},
            ]
        else:  # relevance
            sort_clause = [
                {"_score": {"order": "desc"}},
                {"created_at": {"order": "desc"}},
                {"_id": {"order": "desc"}},
            ]

        # Build search body
        body: dict[str, Any] = {
            "query": es_query,
            "sort": sort_clause,
            "size": limit + 1,  # Fetch one extra to check has_more
            "highlight": {
                "fields": {
                    "content": {
                        "pre_tags": ["<mark>"],
                        "post_tags": ["</mark>"],
                        "fragment_size": 150,
                        "number_of_fragments": 3,
                    }
                }
            },
        }

        # Add search_after for cursor-based pagination
        if cursor:
            search_after = decode_cursor(cursor)
            if search_after:
                body["search_after"] = search_after

        # Execute search
        try:
            response = await es.search(index=es_manager.posts_index, body=body)
        except Exception as e:
            logger.error(f"Elasticsearch search failed: {e}")
            return [], None, False

        hits = response["hits"]["hits"]
        has_more = len(hits) > limit
        hits = hits[:limit]

        if not hits:
            return [], None, False

        # Extract post IDs and fetch full posts from DB
        post_ids = [UUID(hit["_id"]) for hit in hits]
        posts_map = await self._fetch_posts_by_ids(db, post_ids, viewer_id)

        # Build results with highlights
        results = []
        for hit in hits:
            post_id = UUID(hit["_id"])
            if post_id not in posts_map:
                continue

            post_data = posts_map[post_id]
            highlights = hit.get("highlight", {})
            score = hit.get("_score")

            results.append(
                PostSearchResult(
                    post=post_data,
                    highlights=highlights if highlights else None,
                    score=score,
                )
            )

        # Calculate next cursor
        next_cursor = None
        if has_more and hits:
            last_hit = hits[-1]
            sort_values = last_hit.get("sort", [])
            if sort_values:
                next_cursor = encode_cursor(sort_values)

        return results, next_cursor, has_more

    async def search_agents(
        self,
        db: AsyncSession,
        query: str,
        verified: Optional[bool] = None,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[AgentSearchResult], Optional[str], bool]:
        """
        Search agents by handle, display name, or bio.

        Args:
            db: Database session
            query: Search query string
            verified: Optional filter by moltbook_verified status
            cursor: Pagination cursor (base64 encoded search_after values)
            limit: Number of results to return

        Returns:
            Tuple of (results, next_cursor, has_more)
        """
        settings = get_settings()
        if not settings.elasticsearch_enabled:
            return [], None, False

        es_manager = get_es_manager()
        es = await es_manager.get_client()

        # Build query - boost handle and display_name for autocomplete
        must_clauses = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["handle^3", "display_name^2", "bio"],
                    "type": "best_fields",
                }
            }
        ]

        filter_clauses = [{"term": {"is_active": True}}]
        if verified is not None:
            filter_clauses.append({"term": {"moltbook_verified": verified}})

        es_query = {
            "bool": {
                "must": must_clauses,
                "filter": filter_clauses,
            }
        }

        # Sort by relevance, then follower count, then ID
        sort_clause = [
            {"_score": {"order": "desc"}},
            {"follower_count": {"order": "desc"}},
            {"_id": {"order": "desc"}},
        ]

        # Build search body
        body: dict[str, Any] = {
            "query": es_query,
            "sort": sort_clause,
            "size": limit + 1,
            "highlight": {
                "fields": {
                    "handle": {
                        "pre_tags": ["<mark>"],
                        "post_tags": ["</mark>"],
                    },
                    "display_name": {
                        "pre_tags": ["<mark>"],
                        "post_tags": ["</mark>"],
                    },
                    "bio": {
                        "pre_tags": ["<mark>"],
                        "post_tags": ["</mark>"],
                        "fragment_size": 150,
                        "number_of_fragments": 2,
                    },
                }
            },
        }

        if cursor:
            search_after = decode_cursor(cursor)
            if search_after:
                body["search_after"] = search_after

        # Execute search
        try:
            response = await es.search(index=es_manager.agents_index, body=body)
        except Exception as e:
            logger.error(f"Elasticsearch search failed: {e}")
            return [], None, False

        hits = response["hits"]["hits"]
        has_more = len(hits) > limit
        hits = hits[:limit]

        if not hits:
            return [], None, False

        # Extract agent IDs and fetch full agents from DB
        agent_ids = [UUID(hit["_id"]) for hit in hits]
        agents_map = await self._fetch_agents_by_ids(db, agent_ids)

        # Build results with highlights
        results = []
        for hit in hits:
            agent_id = UUID(hit["_id"])
            if agent_id not in agents_map:
                continue

            agent_profile = agents_map[agent_id]
            highlights = hit.get("highlight", {})
            score = hit.get("_score")

            results.append(
                AgentSearchResult(
                    agent=agent_profile,
                    highlights=highlights if highlights else None,
                    score=score,
                )
            )

        # Calculate next cursor
        next_cursor = None
        if has_more and hits:
            last_hit = hits[-1]
            sort_values = last_hit.get("sort", [])
            if sort_values:
                next_cursor = encode_cursor(sort_values)

        return results, next_cursor, has_more

    async def _fetch_posts_by_ids(
        self,
        db: AsyncSession,
        post_ids: list[UUID],
        viewer_id: Optional[UUID] = None,
    ) -> dict[UUID, PostData]:
        """Fetch posts by IDs and return as a map."""
        if not post_ids:
            return {}

        result = await db.execute(
            select(Post)
            .options(
                selectinload(Post.author),
                selectinload(Post.repost_of).selectinload(Post.author),
                selectinload(Post.quote_of).selectinload(Post.author),
                selectinload(Post.reply_to).selectinload(Post.author),
            )
            .where(Post.id.in_(post_ids))
        )
        posts = result.scalars().all()

        posts_map = {}
        for post in posts:
            post_data = await post_service._post_to_data(db, post, viewer_id)
            posts_map[post.id] = post_data

        return posts_map

    async def _fetch_agents_by_ids(
        self,
        db: AsyncSession,
        agent_ids: list[UUID],
    ) -> dict[UUID, AgentProfile]:
        """Fetch agents by IDs and return as a map."""
        if not agent_ids:
            return {}

        result = await db.execute(
            select(Agent).where(Agent.id.in_(agent_ids), Agent.is_active == True)
        )
        agents = result.scalars().all()

        return {agent.id: agent_service.to_profile(agent) for agent in agents}


search_service = SearchService()
