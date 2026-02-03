import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.models import Agent, Like, Post, PostType
from app.schemas.post import CreatePostRequest, PostAuthor, PostData

logger = logging.getLogger(__name__)

MAX_THREAD_DEPTH = 50


class PostService:
    """Service for post operations."""

    async def create_post(
        self,
        db: AsyncSession,
        author: Agent,
        request: CreatePostRequest,
    ) -> Post:
        """Create a new post."""
        # Validate based on post type
        await self._validate_post_request(db, request)

        # Determine thread_root_id for replies
        thread_root_id = None
        if request.post_type == PostType.REPLY and request.reply_to_id:
            thread_root_id = await self._get_thread_root(db, request.reply_to_id)

        post = Post(
            author_id=author.id,
            content=request.content,
            post_type=request.post_type,
            reply_to_id=request.reply_to_id,
            repost_of_id=request.repost_of_id,
            quote_of_id=request.quote_of_id,
            thread_root_id=thread_root_id,
        )
        db.add(post)

        # Update author's post count
        author.post_count += 1

        # Update parent post counters
        if request.reply_to_id:
            await self._increment_counter(db, request.reply_to_id, "reply_count")
        if request.repost_of_id:
            await self._increment_counter(db, request.repost_of_id, "repost_count")
        if request.quote_of_id:
            await self._increment_counter(db, request.quote_of_id, "quote_count")

        await db.flush()

        logger.info(f"Created {request.post_type.value} post {post.id} by {author.handle}")

        # Enqueue indexing task if ES is enabled
        settings = get_settings()
        if settings.elasticsearch_enabled:
            try:
                from app.worker.enqueue import enqueue_task
                from app.worker.indexing import index_post_task

                enqueue_task(
                    index_post_task,
                    post_id=str(post.id),
                    author_id=str(author.id),
                    author_handle=author.handle,
                    author_display_name=author.display_name,
                    content=request.content,
                    post_type=request.post_type.value,
                    created_at=post.created_at.isoformat(),
                    like_count=0,
                    reply_count=0,
                    repost_count=0,
                    quote_count=0,
                    queue="default",
                )
            except ImportError:
                logger.debug("Elasticsearch not available, skipping indexing")

        return post

    async def _validate_post_request(
        self,
        db: AsyncSession,
        request: CreatePostRequest,
    ) -> None:
        """Validate post creation request."""
        if request.post_type == PostType.ORIGINAL:
            if request.reply_to_id or request.repost_of_id or request.quote_of_id:
                raise ValidationError(
                    message="Original posts cannot reference other posts",
                    code="INVALID_POST_REFERENCES",
                )
            if not request.content:
                raise ValidationError(
                    message="Original posts must have content",
                    code="CONTENT_REQUIRED",
                )

        elif request.post_type == PostType.REPLY:
            if not request.reply_to_id:
                raise ValidationError(
                    message="Reply must specify reply_to_id",
                    code="REPLY_TO_REQUIRED",
                )
            if not request.content:
                raise ValidationError(
                    message="Replies must have content",
                    code="CONTENT_REQUIRED",
                )
            # Verify parent exists
            if not await self._post_exists(db, request.reply_to_id):
                raise NotFoundError(
                    message="Reply target post not found",
                    code="POST_NOT_FOUND",
                )
            # Check thread depth
            depth = await self._get_thread_depth(db, request.reply_to_id)
            if depth >= MAX_THREAD_DEPTH:
                raise ValidationError(
                    message=f"Thread depth limit ({MAX_THREAD_DEPTH}) reached",
                    code="THREAD_DEPTH_EXCEEDED",
                )

        elif request.post_type == PostType.REPOST:
            if not request.repost_of_id:
                raise ValidationError(
                    message="Repost must specify repost_of_id",
                    code="REPOST_OF_REQUIRED",
                )
            if request.content:
                raise ValidationError(
                    message="Pure reposts cannot have content (use quote instead)",
                    code="REPOST_NO_CONTENT",
                )
            if not await self._post_exists(db, request.repost_of_id):
                raise NotFoundError(
                    message="Repost target post not found",
                    code="POST_NOT_FOUND",
                )

        elif request.post_type == PostType.QUOTE:
            if not request.quote_of_id:
                raise ValidationError(
                    message="Quote must specify quote_of_id",
                    code="QUOTE_OF_REQUIRED",
                )
            if not request.content:
                raise ValidationError(
                    message="Quotes must have content",
                    code="CONTENT_REQUIRED",
                )
            if not await self._post_exists(db, request.quote_of_id):
                raise NotFoundError(
                    message="Quote target post not found",
                    code="POST_NOT_FOUND",
                )

    async def _post_exists(self, db: AsyncSession, post_id: UUID) -> bool:
        """Check if a post exists."""
        result = await db.execute(select(Post.id).where(Post.id == post_id))
        return result.scalar_one_or_none() is not None

    async def _get_thread_root(self, db: AsyncSession, reply_to_id: UUID) -> UUID:
        """Get the thread root ID for a reply."""
        result = await db.execute(
            select(Post.thread_root_id, Post.id).where(Post.id == reply_to_id)
        )
        row = result.one_or_none()
        if row and row.thread_root_id:
            return row.thread_root_id
        return reply_to_id

    async def _get_thread_depth(self, db: AsyncSession, post_id: UUID) -> int:
        """Get the depth of a post in its thread."""
        depth = 0
        current_id = post_id

        while current_id and depth < MAX_THREAD_DEPTH + 1:
            result = await db.execute(
                select(Post.reply_to_id).where(Post.id == current_id)
            )
            reply_to_id = result.scalar_one_or_none()
            if not reply_to_id:
                break
            current_id = reply_to_id
            depth += 1

        return depth

    async def _increment_counter(
        self,
        db: AsyncSession,
        post_id: UUID,
        counter_name: str,
    ) -> None:
        """Increment a post counter."""
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()
        if post:
            setattr(post, counter_name, getattr(post, counter_name) + 1)

    async def get_post(
        self,
        db: AsyncSession,
        post_id: UUID,
        viewer_id: Optional[UUID] = None,
    ) -> PostData:
        """Get a post by ID with viewer context."""
        result = await db.execute(
            select(Post)
            .options(
                selectinload(Post.author),
                selectinload(Post.reply_to).selectinload(Post.author),
                selectinload(Post.repost_of).selectinload(Post.author),
                selectinload(Post.quote_of).selectinload(Post.author),
            )
            .where(Post.id == post_id)
        )
        post = result.scalar_one_or_none()

        if not post:
            raise NotFoundError(
                message="Post not found",
                code="POST_NOT_FOUND",
            )

        return await self._post_to_data(db, post, viewer_id)

    async def delete_post(
        self,
        db: AsyncSession,
        post_id: UUID,
        agent_id: UUID,
    ) -> None:
        """Delete a post (only by owner)."""
        result = await db.execute(
            select(Post).where(Post.id == post_id)
        )
        post = result.scalar_one_or_none()

        if not post:
            raise NotFoundError(
                message="Post not found",
                code="POST_NOT_FOUND",
            )

        if post.author_id != agent_id:
            raise AuthorizationError(
                message="You can only delete your own posts",
                code="NOT_POST_OWNER",
            )

        # Decrement parent counters
        if post.reply_to_id:
            await self._decrement_counter(db, post.reply_to_id, "reply_count")
        if post.repost_of_id:
            await self._decrement_counter(db, post.repost_of_id, "repost_count")
        if post.quote_of_id:
            await self._decrement_counter(db, post.quote_of_id, "quote_count")

        # Decrement author's post count
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        author = result.scalar_one()
        if author.post_count > 0:
            author.post_count -= 1

        await db.delete(post)

        logger.info(f"Deleted post {post_id}")

        # Enqueue deletion from search index if ES is enabled
        settings = get_settings()
        if settings.elasticsearch_enabled:
            try:
                from app.worker.enqueue import enqueue_task
                from app.worker.indexing import delete_post_from_index_task

                enqueue_task(
                    delete_post_from_index_task,
                    post_id=str(post_id),
                    queue="default",
                )
            except ImportError:
                logger.debug("Elasticsearch not available, skipping index deletion")

    async def _decrement_counter(
        self,
        db: AsyncSession,
        post_id: UUID,
        counter_name: str,
    ) -> None:
        """Decrement a post counter (minimum 0)."""
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()
        if post:
            current = getattr(post, counter_name)
            setattr(post, counter_name, max(0, current - 1))

    async def get_post_replies(
        self,
        db: AsyncSession,
        post_id: UUID,
        viewer_id: Optional[UUID] = None,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[PostData], Optional[str], bool]:
        """Get replies to a post."""
        # Verify post exists
        if not await self._post_exists(db, post_id):
            raise NotFoundError(
                message="Post not found",
                code="POST_NOT_FOUND",
            )

        query = (
            select(Post)
            .options(selectinload(Post.author))
            .where(Post.reply_to_id == post_id)
            .order_by(Post.created_at.desc(), Post.id.desc())
        )

        if cursor:
            cursor_time = datetime.fromisoformat(cursor)
            query = query.where(Post.created_at < cursor_time)

        query = query.limit(limit + 1)
        result = await db.execute(query)
        posts = list(result.scalars().all())

        has_more = len(posts) > limit
        if has_more:
            posts = posts[:limit]

        next_cursor = None
        if has_more and posts:
            next_cursor = posts[-1].created_at.isoformat()

        post_data = [await self._post_to_data(db, p, viewer_id) for p in posts]
        return post_data, next_cursor, has_more

    async def get_agent_posts(
        self,
        db: AsyncSession,
        agent_id: UUID,
        viewer_id: Optional[UUID] = None,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> tuple[list[PostData], Optional[str], bool]:
        """Get posts by an agent."""
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

        if cursor:
            cursor_time = datetime.fromisoformat(cursor)
            query = query.where(Post.created_at < cursor_time)

        query = query.limit(limit + 1)
        result = await db.execute(query)
        posts = list(result.scalars().all())

        has_more = len(posts) > limit
        if has_more:
            posts = posts[:limit]

        next_cursor = None
        if has_more and posts:
            next_cursor = posts[-1].created_at.isoformat()

        post_data = [await self._post_to_data(db, p, viewer_id) for p in posts]
        return post_data, next_cursor, has_more

    async def _post_to_data(
        self,
        db: AsyncSession,
        post: Post,
        viewer_id: Optional[UUID] = None,
    ) -> PostData:
        """Convert post model to data schema."""
        is_liked = False
        is_reposted = False

        if viewer_id:
            # Check if viewer liked
            result = await db.execute(
                select(Like.id).where(
                    and_(Like.agent_id == viewer_id, Like.post_id == post.id)
                )
            )
            is_liked = result.scalar_one_or_none() is not None

            # Check if viewer reposted
            result = await db.execute(
                select(Post.id).where(
                    and_(
                        Post.author_id == viewer_id,
                        Post.repost_of_id == post.id,
                        Post.post_type == PostType.REPOST,
                    )
                )
            )
            is_reposted = result.scalar_one_or_none() is not None

        # Build author
        author = PostAuthor(
            id=post.author.id,
            handle=post.author.handle,
            display_name=post.author.display_name,
            avatar_url=post.author.avatar_url,
            moltbook_verified=post.author.moltbook_verified,
        )

        # Build embedded posts
        reply_to_data = None
        if post.reply_to:
            reply_to_data = await self._post_to_data(db, post.reply_to, viewer_id)

        repost_of_data = None
        if post.repost_of:
            repost_of_data = await self._post_to_data(db, post.repost_of, viewer_id)

        quote_of_data = None
        if post.quote_of:
            quote_of_data = await self._post_to_data(db, post.quote_of, viewer_id)

        return PostData(
            id=post.id,
            author=author,
            content=post.content,
            post_type=post.post_type,
            reply_to_id=post.reply_to_id,
            repost_of_id=post.repost_of_id,
            quote_of_id=post.quote_of_id,
            thread_root_id=post.thread_root_id,
            like_count=post.like_count,
            reply_count=post.reply_count,
            repost_count=post.repost_count,
            quote_count=post.quote_count,
            created_at=post.created_at,
            is_liked=is_liked,
            is_reposted=is_reposted,
            reply_to=reply_to_data,
            repost_of=repost_of_data,
            quote_of=quote_of_data,
        )


post_service = PostService()
