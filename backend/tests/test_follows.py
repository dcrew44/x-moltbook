from uuid import uuid4

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Agent
from app.services.follow_service import follow_service


@pytest.fixture
async def test_agents(db_session) -> tuple[Agent, Agent]:
    """Create two test agents."""
    agent1 = Agent(
        handle="user1",
        display_name="User One",
        moltbook_agent_id=str(uuid4()),
    )
    agent2 = Agent(
        handle="user2",
        display_name="User Two",
        moltbook_agent_id=str(uuid4()),
    )
    db_session.add(agent1)
    db_session.add(agent2)
    await db_session.commit()
    await db_session.refresh(agent1)
    await db_session.refresh(agent2)
    return agent1, agent2


@pytest.mark.asyncio
async def test_follow_agent(db_session, test_agents):
    """Test following an agent."""
    follower, followed = test_agents

    await follow_service.follow(db_session, follower, followed.handle)
    await db_session.commit()
    await db_session.refresh(follower)
    await db_session.refresh(followed)

    assert follower.following_count == 1
    assert followed.follower_count == 1


@pytest.mark.asyncio
async def test_cannot_follow_self(db_session, test_agents):
    """Test that an agent cannot follow themselves."""
    follower, _ = test_agents

    with pytest.raises(ValidationError) as exc_info:
        await follow_service.follow(db_session, follower, follower.handle)

    assert exc_info.value.code == "SELF_FOLLOW"


@pytest.mark.asyncio
async def test_cannot_follow_twice(db_session, test_agents):
    """Test that an agent cannot follow the same agent twice."""
    follower, followed = test_agents

    await follow_service.follow(db_session, follower, followed.handle)
    await db_session.commit()

    with pytest.raises(ConflictError) as exc_info:
        await follow_service.follow(db_session, follower, followed.handle)

    assert exc_info.value.code == "ALREADY_FOLLOWING"


@pytest.mark.asyncio
async def test_unfollow_agent(db_session, test_agents):
    """Test unfollowing an agent."""
    follower, followed = test_agents

    await follow_service.follow(db_session, follower, followed.handle)
    await db_session.commit()

    await follow_service.unfollow(db_session, follower, followed.handle)
    await db_session.commit()
    await db_session.refresh(follower)
    await db_session.refresh(followed)

    assert follower.following_count == 0
    assert followed.follower_count == 0


@pytest.mark.asyncio
async def test_unfollow_not_following(db_session, test_agents):
    """Test unfollowing an agent you're not following."""
    follower, followed = test_agents

    with pytest.raises(NotFoundError) as exc_info:
        await follow_service.unfollow(db_session, follower, followed.handle)

    assert exc_info.value.code == "NOT_FOLLOWING"


@pytest.mark.asyncio
async def test_get_followers(db_session, test_agents):
    """Test getting followers of an agent."""
    follower, followed = test_agents

    await follow_service.follow(db_session, follower, followed.handle)
    await db_session.commit()

    followers, cursor, has_more = await follow_service.get_followers(
        db_session, followed.handle
    )

    assert len(followers) == 1
    assert followers[0].handle == "user1"
    assert has_more is False


@pytest.mark.asyncio
async def test_get_following(db_session, test_agents):
    """Test getting agents that a user follows."""
    follower, followed = test_agents

    await follow_service.follow(db_session, follower, followed.handle)
    await db_session.commit()

    following, cursor, has_more = await follow_service.get_following(
        db_session, follower.handle
    )

    assert len(following) == 1
    assert following[0].handle == "user2"
    assert has_more is False
