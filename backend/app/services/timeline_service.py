import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import Agent, Follow, Post
from app.schemas.post import PostData
from app.services.cache_service import cache_service
from app.services.post_service import post_service

logger = logging.getLogger(__name__)


class TimelineService:
    """Service for timeline operations.

    Uses a hybrid push/pull model:
    - Normal accounts: Posts are pushed to followers' Redis timelines
    - Celebrity accounts (>= threshold followers): Posts are pulled on-demand from DB
    """

    async def get_home_timeline(
        self,
        db: AsyncSession,
        agent_id: UUID,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[PostData], Optional[str], bool]:
        """
        Get home timeline for an agent.

        Combines:
        1. Pushed posts from Redis cache (from non-celebrity followees)
        2. Pulled posts from DB (from celebrity followees)
        3. Own posts

        Uses cursor-based pagination with timestamp_ms as the cursor.
        """
        # Parse cursor (timestamp in milliseconds)
        cursor_ms = None
        cursor_dt = None
        if cursor:
            try:
                cursor_ms = int(cursor)
                cursor_dt = datetime.fromtimestamp(cursor_ms / 1000, tz=timezone.utc)
            except ValueError:
                # Try parsing as ISO timestamp for backwards compatibility
                try:
                    cursor_dt = datetime.fromisoformat(cursor)
                    cursor_ms = int(cursor_dt.timestamp() * 1000)
                except ValueError:
                    pass

        # Get celebrity and non-celebrity followee IDs
        celebrity_ids, non_celebrity_ids = await self._get_followee_ids_by_celebrity_status(
            db, agent_id
        )

        # Fetch from Redis cache (non-celebrity posts from followees)
        cached_ids, _ = await cache_service.get_timeline(
            agent_id,
            limit=limit + 1,  # Fetch extra to check has_more
            max_score=cursor_ms,
        )

        # Fetch celebrity posts from DB (pulled on-demand)
        celebrity_posts = await self._fetch_celebrity_posts(
            db=db,
            celebrity_ids=celebrity_ids,
            viewer_id=agent_id,
            cursor_dt=cursor_dt,
            limit=limit + 1,
        )

        # Fetch own posts from DB (not pushed to own timeline)
        own_posts = await self._fetch_own_posts(
            db=db,
            agent_id=agent_id,
            cursor_dt=cursor_dt,
            limit=limit + 1,
        )

        # Fetch cached posts by IDs
        cached_posts: list[PostData] = []
        if cached_ids:
            cached_posts = await self._fetch_posts_by_ids(db, cached_ids, agent_id)
        elif non_celebrity_ids:
            # Cache miss - fetch non-celebrity followee posts from DB
            cached_posts = await self._fetch_non_celebrity_posts(
                db=db,
                followee_ids=non_celebrity_ids,
                viewer_id=agent_id,
                cursor_dt=cursor_dt,
                limit=limit + 1,
            )

        # Merge and sort all posts by created_at descending, with ID as tiebreaker
        # Normalize timestamps to UTC for comparison (handles both naive and aware datetimes)
        def sort_key(post: PostData):
            ts = post.created_at
            if ts.tzinfo is None:
                # Treat naive datetime as UTC
                ts = ts.replace(tzinfo=timezone.utc)
            return (ts, post.id)

        all_posts = cached_posts + celebrity_posts + own_posts
        all_posts.sort(key=sort_key, reverse=True)

        # Deduplicate (in case own posts appear in both sources)
        seen_ids: set[UUID] = set()
        unique_posts: list[PostData] = []
        for post in all_posts:
            if post.id not in seen_ids:
                seen_ids.add(post.id)
                unique_posts.append(post)

        # Apply pagination
        has_more = len(unique_posts) > limit
        result_posts = unique_posts[:limit]

        # Calculate next cursor
        next_cursor = None
        if has_more and result_posts:
            last_post = result_posts[-1]
            next_cursor = str(int(last_post.created_at.timestamp() * 1000))

        return result_posts, next_cursor, has_more

    async def _get_followee_ids_by_celebrity_status(
        self,
        db: AsyncSession,
        agent_id: UUID,
    ) -> tuple[list[UUID], list[UUID]]:
        """
        Get IDs of followed accounts split by celebrity status.

        Returns:
            Tuple of (celebrity_ids, non_celebrity_ids)
        """
        settings = get_settings()
        threshold = settings.celebrity_follower_threshold

        result = await db.execute(
            select(Follow.followed_id, Agent.follower_count)
            .join(Agent, Agent.id == Follow.followed_id)
            .where(Follow.follower_id == agent_id)
        )

        celebrity_ids: list[UUID] = []
        non_celebrity_ids: list[UUID] = []

        for followed_id, follower_count in result.all():
            if follower_count >= threshold:
                celebrity_ids.append(followed_id)
            else:
                non_celebrity_ids.append(followed_id)

        return celebrity_ids, non_celebrity_ids

    async def _fetch_celebrity_posts(
        self,
        db: AsyncSession,
        celebrity_ids: list[UUID],
        viewer_id: UUID,
        cursor_dt: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[PostData]:
        """Fetch recent posts from celebrity accounts."""
        if not celebrity_ids:
            return []

        query = (
            select(Post)
            .options(
                selectinload(Post.author),
                selectinload(Post.repost_of).selectinload(Post.author),
                selectinload(Post.quote_of).selectinload(Post.author),
            )
            .where(Post.author_id.in_(celebrity_ids))
            .order_by(Post.created_at.desc(), Post.id.desc())
        )

        if cursor_dt:
            query = query.where(Post.created_at < cursor_dt)

        query = query.limit(limit)
        result = await db.execute(query)
        posts = list(result.scalars().all())

        return [await post_service._post_to_data(db, p, viewer_id) for p in posts]

    async def _fetch_own_posts(
        self,
        db: AsyncSession,
        agent_id: UUID,
        cursor_dt: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[PostData]:
        """Fetch agent's own posts for their timeline."""
        query = (
            select(Post)
            .options(
                selectinload(Post.author),
                selectinload(Post.repost_of).selectinload(Post.author),
                selectinload(Post.quote_of).selectinload(Post.author),
            )
            .where(Post.author_id == agent_id)
            .order_by(Post.created_at.desc(), Post.id.desc())
        )

        if cursor_dt:
            query = query.where(Post.created_at < cursor_dt)

        query = query.limit(limit)
        result = await db.execute(query)
        posts = list(result.scalars().all())

        return [await post_service._post_to_data(db, p, agent_id) for p in posts]

    async def _fetch_non_celebrity_posts(
        self,
        db: AsyncSession,
        followee_ids: list[UUID],
        viewer_id: UUID,
        cursor_dt: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[PostData]:
        """Fetch posts from non-celebrity followees (DB fallback when cache misses)."""
        if not followee_ids:
            return []

        query = (
            select(Post)
            .options(
                selectinload(Post.author),
                selectinload(Post.repost_of).selectinload(Post.author),
                selectinload(Post.quote_of).selectinload(Post.author),
            )
            .where(Post.author_id.in_(followee_ids))
            .order_by(Post.created_at.desc(), Post.id.desc())
        )

        if cursor_dt:
            query = query.where(Post.created_at < cursor_dt)

        query = query.limit(limit)
        result = await db.execute(query)
        posts = list(result.scalars().all())

        return [await post_service._post_to_data(db, p, viewer_id) for p in posts]

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
