import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.config import get_settings
from app.models import Agent, Post, PostType
from app.schemas.post import CreatePostRequest
from app.services.follow_service import follow_service
from app.services.post_service import post_service
from app.services.timeline_service import timeline_service
from app.worker.fanout import fanout_to_timelines


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

    # Agent1 creates a newer post with explicit future timestamp
    # to ensure it's definitely newer than agent2's posts
    post = Post(
        author_id=agent1.id,
        content="Newest post",
        post_type=PostType.ORIGINAL,
    )
    # Set timestamp to future to guarantee ordering
    post.created_at = datetime.now(timezone.utc) + timedelta(hours=1)
    post.updated_at = post.created_at
    db_session.add(post)
    agent1.post_count += 1
    await db_session.commit()

    with patch("app.services.cache_service.cache_service.get_timeline", new_callable=AsyncMock, return_value=([], None)):
        posts, cursor, has_more = await timeline_service.get_home_timeline(
            db_session, agent1.id
        )

    # First post should be the newest (Agent1's post)
    assert posts[0].content == "Newest post"
    assert posts[0].author.handle == "timelineuser1"


# =============================================================================
# Hybrid Push/Pull Model Tests
# =============================================================================

@pytest.fixture
async def celebrity_and_normal_agents(db_session):
    """Create a viewer, a celebrity, and a normal user with posts."""
    settings = get_settings()
    threshold = settings.celebrity_follower_threshold

    viewer = Agent(
        handle="viewer",
        display_name="Viewer",
        moltbook_agent_id=str(uuid4()),
    )
    celebrity = Agent(
        handle="celebrity",
        display_name="Celebrity User",
        moltbook_agent_id=str(uuid4()),
        follower_count=threshold + 1000,  # Above threshold
    )
    normal_user = Agent(
        handle="normaluser",
        display_name="Normal User",
        moltbook_agent_id=str(uuid4()),
        follower_count=100,  # Below threshold
    )

    db_session.add(viewer)
    db_session.add(celebrity)
    db_session.add(normal_user)
    await db_session.commit()

    await db_session.refresh(viewer)
    await db_session.refresh(celebrity)
    await db_session.refresh(normal_user)

    # Celebrity creates posts
    for i in range(3):
        await post_service.create_post(
            db_session,
            celebrity,
            CreatePostRequest(content=f"Celebrity post {i}", post_type=PostType.ORIGINAL),
        )

    # Normal user creates posts
    for i in range(3):
        await post_service.create_post(
            db_session,
            normal_user,
            CreatePostRequest(content=f"Normal post {i}", post_type=PostType.ORIGINAL),
        )

    await db_session.commit()
    return viewer, celebrity, normal_user


@pytest.mark.asyncio
async def test_hybrid_timeline_shows_both_celebrity_and_normal_posts(
    db_session, celebrity_and_normal_agents
):
    """Test that timeline shows posts from both celebrities and normal users."""
    viewer, celebrity, normal_user = celebrity_and_normal_agents

    # Viewer follows both celebrity and normal user
    await follow_service.follow(db_session, viewer, celebrity.handle)
    await follow_service.follow(db_session, viewer, normal_user.handle)
    await db_session.commit()

    # Mock Redis cache to return empty (simulating that only normal user posts are in cache)
    # but we'll test full flow where celebrity posts are pulled from DB
    with patch("app.services.cache_service.cache_service.get_timeline", new_callable=AsyncMock, return_value=([], None)):
        posts, cursor, has_more = await timeline_service.get_home_timeline(
            db_session, viewer.id, limit=10
        )

    # Should see posts from both celebrity and normal user
    celebrity_posts = [p for p in posts if p.author.handle == "celebrity"]
    normal_posts = [p for p in posts if p.author.handle == "normaluser"]

    assert len(celebrity_posts) == 3, "Should see 3 celebrity posts"
    assert len(normal_posts) == 3, "Should see 3 normal user posts"
    assert len(posts) == 6, "Should see total of 6 posts"


@pytest.mark.asyncio
async def test_fanout_skipped_for_celebrity(db_session, celebrity_and_normal_agents):
    """Test that fanout is skipped for celebrity accounts."""
    viewer, celebrity, normal_user = celebrity_and_normal_agents
    settings = get_settings()

    # Create a list of follower IDs that exceeds threshold
    follower_ids = [str(uuid4()) for _ in range(settings.celebrity_follower_threshold + 100)]

    # Mock Redis to track calls
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute.return_value = []

    with patch("app.worker.fanout.get_sync_redis", return_value=mock_redis):
        result = fanout_to_timelines(
            post_id=str(uuid4()),
            author_id=str(celebrity.id),
            timestamp_ms=1000000000000,
            target_ids=follower_ids,
        )

    # Fanout should return 0 and NOT call Redis pipeline
    assert result == 0, "Fanout should return 0 for celebrity"
    mock_redis.pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_fanout_executed_for_normal_user(db_session, celebrity_and_normal_agents):
    """Test that fanout is executed for normal (non-celebrity) accounts."""
    viewer, celebrity, normal_user = celebrity_and_normal_agents
    settings = get_settings()

    # Create a list of follower IDs below threshold
    follower_ids = [str(uuid4()) for _ in range(settings.celebrity_follower_threshold - 100)]

    # Mock Redis to track calls
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute.return_value = []

    with patch("app.worker.fanout.get_sync_redis", return_value=mock_redis):
        result = fanout_to_timelines(
            post_id=str(uuid4()),
            author_id=str(normal_user.id),
            timestamp_ms=1000000000000,
            target_ids=follower_ids,
        )

    # Fanout should return number of timelines updated and call Redis
    assert result == len(follower_ids), "Fanout should update all follower timelines"
    mock_redis.pipeline.assert_called_once()
    mock_pipeline.execute.assert_called_once()


@pytest.mark.asyncio
async def test_hybrid_timeline_pagination(db_session):
    """Test pagination works correctly when merging celebrity and cached posts."""
    settings = get_settings()
    threshold = settings.celebrity_follower_threshold

    viewer = Agent(
        handle="pagination_viewer",
        display_name="Pagination Viewer",
        moltbook_agent_id=str(uuid4()),
    )
    celebrity = Agent(
        handle="pagination_celebrity",
        display_name="Pagination Celebrity",
        moltbook_agent_id=str(uuid4()),
        follower_count=threshold + 1,
    )

    db_session.add(viewer)
    db_session.add(celebrity)
    await db_session.commit()
    await db_session.refresh(viewer)
    await db_session.refresh(celebrity)

    # Celebrity creates 10 posts with explicit distinct timestamps
    # (SQLite has second-level precision with func.now(), so we set timestamps manually)
    base_time = datetime.now(timezone.utc)
    created_posts = []
    for i in range(10):
        post = Post(
            author_id=celebrity.id,
            content=f"Page post {i}",
            post_type=PostType.ORIGINAL,
        )
        # Explicitly set created_at with 1-second intervals to ensure distinct timestamps
        post.created_at = base_time - timedelta(seconds=10 - i)
        post.updated_at = post.created_at
        db_session.add(post)
        created_posts.append(post)
    await db_session.commit()

    # Viewer follows celebrity
    await follow_service.follow(db_session, viewer, celebrity.handle)
    await db_session.commit()

    # Get first page (5 posts)
    with patch("app.services.cache_service.cache_service.get_timeline", new_callable=AsyncMock, return_value=([], None)):
        page1_posts, cursor1, has_more1 = await timeline_service.get_home_timeline(
            db_session, viewer.id, limit=5
        )

    assert len(page1_posts) == 5, "First page should have 5 posts"
    assert has_more1, "Should have more posts"
    assert cursor1 is not None, "Should have a cursor for next page"

    # Get second page using cursor
    with patch("app.services.cache_service.cache_service.get_timeline", new_callable=AsyncMock, return_value=([], None)):
        page2_posts, cursor2, has_more2 = await timeline_service.get_home_timeline(
            db_session, viewer.id, cursor=cursor1, limit=5
        )

    assert len(page2_posts) == 5, "Second page should have 5 posts"
    assert not has_more2, "Should not have more posts after second page"

    # Verify no duplicate posts between pages
    page1_ids = {p.id for p in page1_posts}
    page2_ids = {p.id for p in page2_posts}
    assert page1_ids.isdisjoint(page2_ids), "Pages should have no overlapping posts"

    # Verify all 10 posts are covered
    all_ids = page1_ids | page2_ids
    assert len(all_ids) == 10, "Both pages combined should cover all 10 posts"


@pytest.mark.asyncio
async def test_celebrity_threshold_boundary(db_session):
    """Test the exact boundary of celebrity threshold."""
    settings = get_settings()
    threshold = settings.celebrity_follower_threshold

    # Test with exactly threshold followers (should skip)
    at_threshold_ids = [str(uuid4()) for _ in range(threshold)]

    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute.return_value = []

    with patch("app.worker.fanout.get_sync_redis", return_value=mock_redis):
        result = fanout_to_timelines(
            post_id=str(uuid4()),
            author_id=str(uuid4()),
            timestamp_ms=1000000000000,
            target_ids=at_threshold_ids,
        )

    assert result == 0, "Fanout should be skipped at exactly threshold"
    mock_redis.pipeline.assert_not_called()

    # Test with one less than threshold (should execute)
    below_threshold_ids = [str(uuid4()) for _ in range(threshold - 1)]

    mock_redis2 = MagicMock()
    mock_pipeline2 = MagicMock()
    mock_redis2.pipeline.return_value = mock_pipeline2
    mock_pipeline2.execute.return_value = []

    with patch("app.worker.fanout.get_sync_redis", return_value=mock_redis2):
        result2 = fanout_to_timelines(
            post_id=str(uuid4()),
            author_id=str(uuid4()),
            timestamp_ms=1000000000000,
            target_ids=below_threshold_ids,
        )

    assert result2 == threshold - 1, "Fanout should execute below threshold"
    mock_redis2.pipeline.assert_called_once()


@pytest.mark.asyncio
async def test_hybrid_timeline_deduplication(db_session):
    """Test that duplicate posts are properly deduplicated in the merged timeline."""
    settings = get_settings()
    threshold = settings.celebrity_follower_threshold

    viewer = Agent(
        handle="dedup_viewer",
        display_name="Dedup Viewer",
        moltbook_agent_id=str(uuid4()),
    )
    celebrity = Agent(
        handle="dedup_celebrity",
        display_name="Dedup Celebrity",
        moltbook_agent_id=str(uuid4()),
        follower_count=threshold + 1,
    )

    db_session.add(viewer)
    db_session.add(celebrity)
    await db_session.commit()
    await db_session.refresh(viewer)
    await db_session.refresh(celebrity)

    # Celebrity creates a post
    post = await post_service.create_post(
        db_session,
        celebrity,
        CreatePostRequest(content="Dedup test post", post_type=PostType.ORIGINAL),
    )
    await db_session.commit()

    # Viewer follows celebrity
    await follow_service.follow(db_session, viewer, celebrity.handle)
    await db_session.commit()

    # Mock cache to return the same post ID (simulating it being in both cache and DB pull)
    with patch(
        "app.services.cache_service.cache_service.get_timeline",
        new_callable=AsyncMock,
        return_value=([post.id], None),
    ):
        posts, cursor, has_more = await timeline_service.get_home_timeline(
            db_session, viewer.id, limit=10
        )

    # Should only have 1 post (deduplicated)
    assert len(posts) == 1, "Should have only 1 post after deduplication"
    assert posts[0].content == "Dedup test post"
