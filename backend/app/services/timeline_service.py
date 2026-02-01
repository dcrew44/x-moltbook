import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Follow, Post
from app.schemas.post import PostData
from app.services.cache_service import cache_service
from app.services.post_service import post_service

logger = logging.getLogger(__name__)


class TimelineService:
    """Service for timeline operations."""

    async def get_home_timeline(
        self,
        db: AsyncSession,
        agent_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[PostData], Optional[str], bool]:
        """
        Get home timeline for an agent.

        Combines posts from followed agents and own posts.
        Uses cache when available, falls back to database.
        """
        # Try cache first
        cursor_score = None
        if cursor:
            try:
                cursor_score = int(cursor)
            except ValueError:
                # Fall back to timestamp-based cursor for DB
                pass

        cached_ids, next_cache_cursor = await cache_service.get_timeline(
            agent_id,
            limit=limit,
            max_score=cursor_score,
        )

        if cached_ids:
            # Fetch posts by IDs from database
            posts = await self._fetch_posts_by_ids(db, cached_ids, agent_id)

            # Sort by created_at descending to maintain order
            posts.sort(key=lambda p: p.created_at, reverse=True)

            has_more = next_cache_cursor is not None
            next_cursor = str(next_cache_cursor) if next_cache_cursor else None

            return posts, next_cursor, has_more

        # Cache miss - fetch from database
        return await self._fetch_timeline_from_db(
            db=db,
            agent_id=agent_id,
            cursor=cursor,
            limit=limit,
        )

    async def _fetch_timeline_from_db(
        self,
        db: AsyncSession,
        agent_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[PostData], Optional[str], bool]:
        """Fetch timeline directly from database."""
        # Get followed agent IDs
        result = await db.execute(
            select(Follow.followed_id).where(Follow.follower_id == agent_id)
        )
        followed_ids = [row[0] for row in result.all()]

        # Include own posts
        author_ids = followed_ids + [agent_id]

        # Build query
        query = (
            select(Post)
            .options(
                selectinload(Post.author),
                selectinload(Post.repost_of).selectinload(Post.author),
                selectinload(Post.quote_of).selectinload(Post.author),
            )
            .where(Post.author_id.in_(author_ids))
            .order_by(Post.created_at.desc(), Post.id.desc())
        )

        if cursor:
            try:
                cursor_time = datetime.fromisoformat(cursor)
                query = query.where(Post.created_at < cursor_time)
            except ValueError:
                pass  # Invalid cursor, ignore

        query = query.limit(limit + 1)
        result = await db.execute(query)
        posts = list(result.scalars().all())

        has_more = len(posts) > limit
        if has_more:
            posts = posts[:limit]

        next_cursor = None
        if has_more and posts:
            next_cursor = posts[-1].created_at.isoformat()

        post_data = [await post_service._post_to_data(db, p, agent_id) for p in posts]
        return post_data, next_cursor, has_more

    async def _fetch_posts_by_ids(
        self,
        db: AsyncSession,
        post_ids: list[UUID],
        viewer_id: UUID,
    ) -> list[PostData]:
        """Fetch posts by IDs and convert to PostData."""
        if not post_ids:
            return []

        result = await db.execute(
            select(Post)
            .options(
                selectinload(Post.author),
                selectinload(Post.repost_of).selectinload(Post.author),
                selectinload(Post.quote_of).selectinload(Post.author),
            )
            .where(Post.id.in_(post_ids))
        )
        posts = {p.id: p for p in result.scalars().all()}

        # Maintain order from post_ids
        ordered_posts = [posts[pid] for pid in post_ids if pid in posts]

        return [await post_service._post_to_data(db, p, viewer_id) for p in ordered_posts]


timeline_service = TimelineService()
