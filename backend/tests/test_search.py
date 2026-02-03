"""Tests for search functionality."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import Agent, Post, PostType
from app.services.search_service import decode_cursor, encode_cursor, search_service


@pytest.fixture
async def test_agent(db_session) -> Agent:
    """Create a test agent."""
    agent = Agent(
        handle="searchuser",
        display_name="Search User",
        bio="I love testing search functionality",
        moltbook_agent_id=str(uuid4()),
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.fixture
async def test_agent_2(db_session) -> Agent:
    """Create a second test agent."""
    agent = Agent(
        handle="anotheruser",
        display_name="Another User",
        bio="Python developer and coffee enthusiast",
        moltbook_verified=True,
        moltbook_agent_id=str(uuid4()),
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.fixture
async def test_posts(db_session, test_agent, test_agent_2) -> list[Post]:
    """Create test posts for search."""
    from app.services.post_service import post_service
    from app.schemas.post import CreatePostRequest

    posts = []

    # Create posts with searchable content
    post1 = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(
            content="Learning Python is fun and exciting!",
            post_type=PostType.ORIGINAL,
        ),
    )
    posts.append(post1)

    post2 = await post_service.create_post(
        db_session,
        test_agent,
        CreatePostRequest(
            content="Just discovered a great JavaScript library for testing",
            post_type=PostType.ORIGINAL,
        ),
    )
    posts.append(post2)

    post3 = await post_service.create_post(
        db_session,
        test_agent_2,
        CreatePostRequest(
            content="Python and coffee make the perfect combination",
            post_type=PostType.ORIGINAL,
        ),
    )
    posts.append(post3)

    await db_session.commit()
    return posts


class TestCursorEncoding:
    """Test cursor encoding/decoding utilities."""

    def test_encode_decode_cursor(self):
        """Test encoding and decoding cursor values."""
        sort_values = [1.5, "2023-01-01T00:00:00Z", "abc123"]
        cursor = encode_cursor(sort_values)

        decoded = decode_cursor(cursor)
        assert decoded == sort_values

    def test_decode_invalid_cursor(self):
        """Test decoding invalid cursor returns None."""
        assert decode_cursor("invalid-cursor") is None
        assert decode_cursor("") is None

    def test_encode_empty_list(self):
        """Test encoding empty list."""
        cursor = encode_cursor([])
        assert decode_cursor(cursor) == []


class TestSearchPosts:
    """Test post search functionality."""

    @pytest.mark.asyncio
    async def test_search_posts_disabled(self, db_session):
        """Test search returns empty when Elasticsearch is disabled."""
        # Default test config has ES disabled
        results, cursor, has_more = await search_service.search_posts(
            db=db_session,
            query="python",
        )

        assert results == []
        assert cursor is None
        assert has_more is False

    @pytest.mark.asyncio
    async def test_search_posts_with_results(self, db_session, test_posts):
        """Test search posts returns results from Elasticsearch."""
        post = test_posts[0]

        # Mock Elasticsearch response
        mock_es = AsyncMock()
        mock_es.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": str(post.id),
                        "_score": 1.5,
                        "highlight": {"content": ["<mark>Python</mark> is fun"]},
                        "sort": [1.5, "2023-01-01T00:00:00Z", str(post.id)],
                    }
                ]
            }
        })

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.posts_index = "test_posts"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                results, cursor, has_more = await search_service.search_posts(
                    db=db_session,
                    query="python",
                )

        assert len(results) == 1
        assert results[0].post.content == post.content
        assert results[0].highlights == {"content": ["<mark>Python</mark> is fun"]}
        assert results[0].score == 1.5
        assert has_more is False

    @pytest.mark.asyncio
    async def test_search_posts_pagination(self, db_session, test_posts):
        """Test search posts with pagination."""
        post1, post2 = test_posts[0], test_posts[1]

        mock_es = AsyncMock()
        # Return limit+1 results to indicate has_more
        mock_es.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": str(post1.id),
                        "_score": 2.0,
                        "sort": [2.0, "2023-01-01T00:00:00Z", str(post1.id)],
                    },
                    {
                        "_id": str(post2.id),
                        "_score": 1.5,
                        "sort": [1.5, "2023-01-01T00:00:00Z", str(post2.id)],
                    },
                ]
            }
        })

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.posts_index = "test_posts"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                results, cursor, has_more = await search_service.search_posts(
                    db=db_session,
                    query="test",
                    limit=1,
                )

        assert len(results) == 1
        assert has_more is True
        assert cursor is not None

    @pytest.mark.asyncio
    async def test_search_posts_filter_by_author(self, db_session, test_posts, test_agent):
        """Test search posts filtered by author handle."""
        post = test_posts[0]

        mock_es = AsyncMock()
        mock_es.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": str(post.id),
                        "_score": 1.0,
                        "sort": [1.0, "2023-01-01T00:00:00Z", str(post.id)],
                    }
                ]
            }
        })

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.posts_index = "test_posts"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                results, cursor, has_more = await search_service.search_posts(
                    db=db_session,
                    query="python",
                    author=test_agent.handle,
                )

        # Verify the filter clause was included in the ES query
        call_args = mock_es.search.call_args
        body = call_args.kwargs.get("body")
        assert any(
            f.get("term", {}).get("author_handle.keyword") == test_agent.handle
            for f in body["query"]["bool"].get("filter", [])
        )

    @pytest.mark.asyncio
    async def test_search_posts_sort_by_recent(self, db_session, test_posts):
        """Test search posts sorted by recency."""
        mock_es = AsyncMock()
        mock_es.search = AsyncMock(return_value={"hits": {"hits": []}})

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.posts_index = "test_posts"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                await search_service.search_posts(
                    db=db_session,
                    query="python",
                    sort="recent",
                )

        call_args = mock_es.search.call_args
        body = call_args.kwargs.get("body")
        # Recent sort should have created_at first
        assert body["sort"][0] == {"created_at": {"order": "desc"}}

    @pytest.mark.asyncio
    async def test_search_posts_elasticsearch_error(self, db_session):
        """Test search gracefully handles Elasticsearch errors."""
        mock_es = AsyncMock()
        mock_es.search = AsyncMock(side_effect=Exception("Connection failed"))

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.posts_index = "test_posts"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                results, cursor, has_more = await search_service.search_posts(
                    db=db_session,
                    query="python",
                )

        # Should return empty results on error, not raise
        assert results == []
        assert cursor is None
        assert has_more is False


class TestSearchAgents:
    """Test agent search functionality."""

    @pytest.mark.asyncio
    async def test_search_agents_disabled(self, db_session):
        """Test agent search returns empty when Elasticsearch is disabled."""
        results, cursor, has_more = await search_service.search_agents(
            db=db_session,
            query="test",
        )

        assert results == []
        assert cursor is None
        assert has_more is False

    @pytest.mark.asyncio
    async def test_search_agents_with_results(self, db_session, test_agent):
        """Test agent search returns results from Elasticsearch."""
        mock_es = AsyncMock()
        mock_es.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": str(test_agent.id),
                        "_score": 2.0,
                        "highlight": {"handle": ["<mark>search</mark>user"]},
                        "sort": [2.0, 0, str(test_agent.id)],
                    }
                ]
            }
        })

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.agents_index = "test_agents"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                results, cursor, has_more = await search_service.search_agents(
                    db=db_session,
                    query="search",
                )

        assert len(results) == 1
        assert results[0].agent.handle == test_agent.handle
        assert results[0].highlights == {"handle": ["<mark>search</mark>user"]}
        assert results[0].score == 2.0

    @pytest.mark.asyncio
    async def test_search_agents_filter_verified(self, db_session, test_agent_2):
        """Test agent search filtered by verified status."""
        mock_es = AsyncMock()
        mock_es.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": str(test_agent_2.id),
                        "_score": 1.0,
                        "sort": [1.0, 0, str(test_agent_2.id)],
                    }
                ]
            }
        })

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.agents_index = "test_agents"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                results, cursor, has_more = await search_service.search_agents(
                    db=db_session,
                    query="another",
                    verified=True,
                )

        call_args = mock_es.search.call_args
        body = call_args.kwargs.get("body")
        filter_clauses = body["query"]["bool"]["filter"]
        assert any(
            f.get("term", {}).get("moltbook_verified") is True
            for f in filter_clauses
        )

    @pytest.mark.asyncio
    async def test_search_agents_pagination(self, db_session, test_agent, test_agent_2):
        """Test agent search with pagination."""
        mock_es = AsyncMock()
        mock_es.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": str(test_agent.id),
                        "_score": 2.0,
                        "sort": [2.0, 0, str(test_agent.id)],
                    },
                    {
                        "_id": str(test_agent_2.id),
                        "_score": 1.5,
                        "sort": [1.5, 0, str(test_agent_2.id)],
                    },
                ]
            }
        })

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.agents_index = "test_agents"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                results, cursor, has_more = await search_service.search_agents(
                    db=db_session,
                    query="user",
                    limit=1,
                )

        assert len(results) == 1
        assert has_more is True
        assert cursor is not None

    @pytest.mark.asyncio
    async def test_search_agents_with_cursor(self, db_session, test_agent):
        """Test agent search using cursor for pagination."""
        cursor_values = [1.5, 0, "prev-id"]
        cursor = encode_cursor(cursor_values)

        mock_es = AsyncMock()
        mock_es.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": str(test_agent.id),
                        "_score": 1.0,
                        "sort": [1.0, 0, str(test_agent.id)],
                    }
                ]
            }
        })

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.agents_index = "test_agents"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                await search_service.search_agents(
                    db=db_session,
                    query="user",
                    cursor=cursor,
                )

        call_args = mock_es.search.call_args
        body = call_args.kwargs.get("body")
        assert body["search_after"] == cursor_values

    @pytest.mark.asyncio
    async def test_search_agents_elasticsearch_error(self, db_session):
        """Test agent search gracefully handles Elasticsearch errors."""
        mock_es = AsyncMock()
        mock_es.search = AsyncMock(side_effect=Exception("Connection failed"))

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.agents_index = "test_agents"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                results, cursor, has_more = await search_service.search_agents(
                    db=db_session,
                    query="test",
                )

        assert results == []
        assert cursor is None
        assert has_more is False

    @pytest.mark.asyncio
    async def test_search_agents_excludes_inactive(self, db_session, test_agent):
        """Test agent search only includes active agents in filter."""
        mock_es = AsyncMock()
        mock_es.search = AsyncMock(return_value={"hits": {"hits": []}})

        mock_es_manager = MagicMock()
        mock_es_manager.get_client = AsyncMock(return_value=mock_es)
        mock_es_manager.agents_index = "test_agents"

        with patch("app.services.search_service.get_settings") as mock_settings:
            mock_settings.return_value.elasticsearch_enabled = True
            with patch("app.services.search_service.get_es_manager", return_value=mock_es_manager):
                await search_service.search_agents(
                    db=db_session,
                    query="test",
                )

        call_args = mock_es.search.call_args
        body = call_args.kwargs.get("body")
        filter_clauses = body["query"]["bool"]["filter"]
        assert any(
            f.get("term", {}).get("is_active") is True
            for f in filter_clauses
        )
