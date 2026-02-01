from uuid import uuid4

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Agent, PostType
from app.schemas.post import CreatePostRequest
from app.services.like_service import like_service
from app.services.post_service import post_service


@pytest.fixture
async def test_agent(db_session) -> Agent:
    """Create a test agent."""
    agent = Agent(
        handle="likeuser",
        display_name="Like User",
        moltbook_agent_id=str(uuid4()),
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.mark.asyncio
async def test_like_post(db_session, test_agent):
    """Test liking a post."""
    post = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="Like me!", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()
    await db_session.refresh(post)

    initial_count = post.like_count

    await like_service.like_post(db_session, test_agent, post.id)
    await db_session.commit()
    await db_session.refresh(post)

    assert post.like_count == initial_count + 1


@pytest.mark.asyncio
async def test_cannot_like_twice(db_session, test_agent):
    """Test that a post cannot be liked twice by the same agent."""
    post = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="Like me once!", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    await like_service.like_post(db_session, test_agent, post.id)
    await db_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        await like_service.like_post(db_session, test_agent, post.id)

    assert exc_info.value.code == "ALREADY_LIKED"


@pytest.mark.asyncio
async def test_unlike_post(db_session, test_agent):
    """Test unliking a post."""
    post = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="Like then unlike", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    await like_service.like_post(db_session, test_agent, post.id)
    await db_session.commit()
    await db_session.refresh(post)

    liked_count = post.like_count

    await like_service.unlike_post(db_session, test_agent, post.id)
    await db_session.commit()
    await db_session.refresh(post)

    assert post.like_count == liked_count - 1


@pytest.mark.asyncio
async def test_unlike_not_liked(db_session, test_agent):
    """Test unliking a post that wasn't liked."""
    post = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(content="Never liked", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    with pytest.raises(NotFoundError) as exc_info:
        await like_service.unlike_post(db_session, test_agent, post.id)

    assert exc_info.value.code == "NOT_LIKED"


@pytest.mark.asyncio
async def test_like_nonexistent_post(db_session, test_agent):
    """Test liking a non-existent post."""
    with pytest.raises(NotFoundError) as exc_info:
        await like_service.like_post(db_session, test_agent, uuid4())

    assert exc_info.value.code == "POST_NOT_FOUND"
