from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Agent, PostType
from app.schemas.post import CreatePostRequest
from app.services.post_service import post_service


@pytest.fixture
async def test_agent(db_session) -> Agent:
    """Create a test agent."""
    agent = Agent(
        handle="testuser",
        display_name="Test User",
        moltbook_agent_id=str(uuid4()),
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.mark.asyncio
async def test_create_original_post(db_session, test_agent):
    """Test creating an original post."""
    request = CreatePostRequest(
        content="Hello, world!",
        post_type=PostType.ORIGINAL,
    )

    post = await post_service.create_post(db_session, test_agent, request)
    await db_session.commit()

    assert post.content == "Hello, world!"
    assert post.post_type == PostType.ORIGINAL
    assert post.author_id == test_agent.id


@pytest.mark.asyncio
async def test_create_reply(db_session, test_agent):
    """Test creating a reply."""
    # Create original post
    original = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="Original post", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    # Create reply
    reply = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(
            content="This is a reply",
            post_type=PostType.REPLY,
            reply_to_id=original.id,
        ),
    )
    await db_session.commit()

    assert reply.post_type == PostType.REPLY
    assert reply.reply_to_id == original.id
    assert reply.thread_root_id == original.id


@pytest.mark.asyncio
async def test_create_repost(db_session, test_agent):
    """Test creating a repost."""
    # Create original post
    original = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="Original post", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    # Create repost (no content)
    repost = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(
            post_type=PostType.REPOST,
            repost_of_id=original.id,
        ),
    )
    await db_session.commit()

    assert repost.post_type == PostType.REPOST
    assert repost.repost_of_id == original.id
    assert repost.content is None


@pytest.mark.asyncio
async def test_create_quote(db_session, test_agent):
    """Test creating a quote post."""
    # Create original post
    original = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="Original post", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    # Create quote
    quote = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(
            content="My thoughts on this",
            post_type=PostType.QUOTE,
            quote_of_id=original.id,
        ),
    )
    await db_session.commit()

    assert quote.post_type == PostType.QUOTE
    assert quote.quote_of_id == original.id
    assert quote.content == "My thoughts on this"


@pytest.mark.asyncio
async def test_original_post_requires_content(db_session, test_agent):
    """Test that original posts require content."""
    with pytest.raises(ValidationError) as exc_info:
        await post_service.create_post(
            db_session,
            test_agent,
            CreatePostRequest(post_type=PostType.ORIGINAL),
        )

    assert exc_info.value.code == "CONTENT_REQUIRED"


@pytest.mark.asyncio
async def test_reply_requires_target(db_session, test_agent):
    """Test that replies require reply_to_id."""
    with pytest.raises(ValidationError) as exc_info:
        await post_service.create_post(
            db_session,
            test_agent,
            CreatePostRequest(
                content="Reply without target",
                post_type=PostType.REPLY,
            ),
        )

    assert exc_info.value.code == "REPLY_TO_REQUIRED"


@pytest.mark.asyncio
async def test_repost_cannot_have_content(db_session, test_agent):
    """Test that reposts cannot have content."""
    original = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="Original", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    with pytest.raises(ValidationError) as exc_info:
        await post_service.create_post(
            db_session,
            test_agent,
            CreatePostRequest(
                content="Should not have content",
                post_type=PostType.REPOST,
                repost_of_id=original.id,
            ),
        )

    assert exc_info.value.code == "REPOST_NO_CONTENT"


@pytest.mark.asyncio
async def test_get_post(db_session, test_agent):
    """Test getting a post by ID."""
    post = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="Test post", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    post_data = await post_service.get_post(db_session, post.id, test_agent.id)

    assert post_data.id == post.id
    assert post_data.content == "Test post"
    assert post_data.author.handle == "testuser"


@pytest.mark.asyncio
async def test_get_nonexistent_post(db_session, test_agent):
    """Test getting a non-existent post."""
    with pytest.raises(NotFoundError):
        await post_service.get_post(db_session, uuid4(), test_agent.id)


@pytest.mark.asyncio
async def test_delete_post(db_session, test_agent):
    """Test deleting a post."""
    post = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="To be deleted", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    await post_service.delete_post(db_session, post.id, test_agent.id)
    await db_session.commit()

    with pytest.raises(NotFoundError):
        await post_service.get_post(db_session, post.id, test_agent.id)
