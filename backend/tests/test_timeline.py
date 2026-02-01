from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models import Agent, PostType
from app.schemas.post import CreatePostRequest
from app.services.follow_service import follow_service
from app.services.post_service import post_service
from app.services.timeline_service import timeline_service


@pytest.fixture
async def test_agents_with_posts(db_session):
    """Create test agents with posts."""
    agent1 = Agent(
        handle="timelineuser1",
        display_name="Timeline User 1",
        moltbook_agent_id=str(uuid4()),
    )
    agent2 = Agent(
        handle="timelineuser2",
        display_name="Timeline User 2",
        moltbook_agent_id=str(uuid4()),
    )
    db_session.add(agent1)
    db_session.add(agent2)
    await db_session.commit()
    await db_session.refresh(agent1)
    await db_session.refresh(agent2)

    # Agent2 creates some posts
    for i in range(3):
        await post_service.create_post(
            db_session,
            agent2,
            CreatePostRequest(content=f"Post {i}", post_type=PostType.ORIGINAL),
        )
    await db_session.commit()

    return agent1, agent2


@pytest.mark.asyncio
async def test_empty_timeline(db_session, test_agents_with_posts):
    """Test timeline for user with no follows."""
    agent1, agent2 = test_agents_with_posts

    # Agent1's own posts only (none)
    with patch("app.services.cache_service.cache_service.get_timeline", new_callable=AsyncMock, return_value=([], None)):
        posts, cursor, has_more = await timeline_service.get_home_timeline(
            db_session, agent1.id
        )

    # Should only see own posts (none)
    assert len(posts) == 0


@pytest.mark.asyncio
async def test_timeline_with_follows(db_session, test_agents_with_posts):
    """Test timeline includes posts from followed agents."""
    agent1, agent2 = test_agents_with_posts

    # Agent1 follows Agent2
    await follow_service.follow(db_session, agent1, agent2.handle)
    await db_session.commit()

    # Now Agent1's timeline should include Agent2's posts
    with patch("app.services.cache_service.cache_service.get_timeline", new_callable=AsyncMock, return_value=([], None)):
        posts, cursor, has_more = await timeline_service.get_home_timeline(
            db_session, agent1.id
        )

    assert len(posts) == 3
    for post in posts:
        assert post.author.handle == "timelineuser2"


@pytest.mark.asyncio
async def test_timeline_includes_own_posts(db_session, test_agents_with_posts):
    """Test timeline includes own posts."""
    agent1, agent2 = test_agents_with_posts

    # Agent1 creates a post
    await post_service.create_post(
        db_session,
        agent1,
        CreatePostRequest(content="My own post", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    with patch("app.services.cache_service.cache_service.get_timeline", new_callable=AsyncMock, return_value=([], None)):
        posts, cursor, has_more = await timeline_service.get_home_timeline(
            db_session, agent1.id
        )

    assert len(posts) == 1
    assert posts[0].content == "My own post"


@pytest.mark.asyncio
async def test_timeline_ordering(db_session, test_agents_with_posts):
    """Test timeline is ordered by recency."""
    agent1, agent2 = test_agents_with_posts

    await follow_service.follow(db_session, agent1, agent2.handle)
    await db_session.commit()

    # Agent1 creates a newer post
    await post_service.create_post(
        db_session,
        agent1,
        CreatePostRequest(content="Newest post", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    with patch("app.services.cache_service.cache_service.get_timeline", new_callable=AsyncMock, return_value=([], None)):
        posts, cursor, has_more = await timeline_service.get_home_timeline(
            db_session, agent1.id
        )

    # First post should be the newest (Agent1's post)
    assert posts[0].content == "Newest post"
    assert posts[0].author.handle == "timelineuser1"
