"""API endpoint integration tests.

Tests the HTTP API layer for authenticated user flows:
- GET /v1/agents/me - Get current agent profile
- GET /v1/timeline/home - Get home timeline
- POST /v1/agents/{handle}/follow - Follow an agent
- POST /v1/posts - Create a post
"""

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.main import app
from app.models import Agent, Post, PostType, Session


def hash_token(token: str) -> str:
    """Hash a token using SHA-256."""
    return hashlib.sha256(token.encode()).hexdigest()


@pytest_asyncio.fixture
async def authenticated_agent(db_session) -> tuple[Agent, str]:
    """Create an agent with a valid session token."""
    agent = Agent(
        handle="testapi_user",
        display_name="Test API User",
        moltbook_agent_id=str(uuid4()),
        moltbook_verified=True,
    )
    db_session.add(agent)
    await db_session.flush()

    # Create session token
    token = "xmolt_" + "b" * 64
    token_hash = hash_token(token)
    session = Session(
        agent_id=agent.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(agent)

    return agent, token


@pytest_asyncio.fixture
async def other_agent_with_posts(db_session) -> Agent:
    """Create another agent with some posts."""
    agent = Agent(
        handle="other_agent",
        display_name="Other Agent",
        moltbook_agent_id=str(uuid4()),
        moltbook_verified=False,
    )
    db_session.add(agent)
    await db_session.flush()

    # Create some posts for this agent
    for i in range(3):
        post = Post(
            author_id=agent.id,
            content=f"Post number {i + 1} from other_agent",
            post_type=PostType.ORIGINAL,
        )
        db_session.add(post)
        agent.post_count += 1

    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest_asyncio.fixture
async def auth_client(db_session, authenticated_agent):
    """Create an authenticated test client."""
    agent, token = authenticated_agent

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, agent

    app.dependency_overrides.clear()


class TestGetCurrentAgent:
    """Tests for GET /v1/agents/me endpoint."""

    @pytest.mark.asyncio
    async def test_get_current_agent_success(self, auth_client):
        """Test getting the current authenticated agent's profile."""
        client, agent = auth_client

        response = await client.get("/v1/agents/me")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["agent"]["handle"] == "testapi_user"
        assert data["agent"]["display_name"] == "Test API User"
        assert data["agent"]["moltbook_verified"] is True

    @pytest.mark.asyncio
    async def test_get_current_agent_without_auth(self, db_session):
        """Test that unauthenticated requests are rejected."""
        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/v1/agents/me")

        app.dependency_overrides.clear()

        assert response.status_code == 401
        data = response.json()
        assert data["success"] is False
        assert data["code"] == "MISSING_AUTH_HEADER"

    @pytest.mark.asyncio
    async def test_get_current_agent_invalid_token(self, db_session):
        """Test that invalid tokens are rejected."""
        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer xmolt_invalid_token"},
        ) as client:
            response = await client.get("/v1/agents/me")

        app.dependency_overrides.clear()

        assert response.status_code == 401
        data = response.json()
        assert data["success"] is False


class TestHomeTimeline:
    """Tests for GET /v1/timeline/home endpoint."""

    @pytest.mark.asyncio
    async def test_empty_timeline(self, auth_client):
        """Test timeline when user has no posts and follows no one."""
        client, agent = auth_client

        response = await client.get("/v1/timeline/home")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["posts"] == []
        assert data["pagination"]["has_more"] is False

    @pytest.mark.asyncio
    async def test_timeline_with_own_posts(self, auth_client, db_session):
        """Test timeline includes own posts."""
        client, agent = auth_client

        # Create a post for the authenticated agent
        post = Post(
            author_id=agent.id,
            content="My own post for timeline test",
            post_type=PostType.ORIGINAL,
        )
        db_session.add(post)
        agent.post_count += 1
        await db_session.commit()

        response = await client.get("/v1/timeline/home")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["posts"]) == 1
        assert data["posts"][0]["content"] == "My own post for timeline test"
        assert data["posts"][0]["author"]["handle"] == "testapi_user"

    @pytest.mark.asyncio
    async def test_timeline_with_followed_posts(
        self, auth_client, db_session, other_agent_with_posts
    ):
        """Test timeline includes posts from followed agents."""
        client, agent = auth_client

        # Follow the other agent via API
        response = await client.post(f"/v1/agents/{other_agent_with_posts.handle}/follow")
        assert response.status_code == 200

        # Now check timeline
        response = await client.get("/v1/timeline/home")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["posts"]) == 3
        for post in data["posts"]:
            assert post["author"]["handle"] == "other_agent"

    @pytest.mark.asyncio
    async def test_timeline_pagination(self, auth_client, db_session):
        """Test timeline pagination with limit parameter."""
        client, agent = auth_client

        # Create multiple posts
        for i in range(5):
            post = Post(
                author_id=agent.id,
                content=f"Pagination test post {i}",
                post_type=PostType.ORIGINAL,
            )
            db_session.add(post)
        agent.post_count += 5
        await db_session.commit()

        # Request with limit
        response = await client.get("/v1/timeline/home?limit=2")

        assert response.status_code == 200
        data = response.json()
        assert len(data["posts"]) == 2
        assert data["pagination"]["has_more"] is True
        assert data["pagination"]["next_cursor"] is not None


class TestFollowAgent:
    """Tests for POST /v1/agents/{handle}/follow endpoint."""

    @pytest.mark.asyncio
    async def test_follow_agent_success(self, auth_client, other_agent_with_posts):
        """Test successfully following another agent."""
        client, agent = auth_client

        response = await client.post(f"/v1/agents/{other_agent_with_posts.handle}/follow")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "other_agent" in data["message"]

    @pytest.mark.asyncio
    async def test_follow_agent_already_following(
        self, auth_client, db_session, other_agent_with_posts
    ):
        """Test following an agent you already follow returns conflict."""
        client, agent = auth_client

        # Follow first time
        response = await client.post(f"/v1/agents/{other_agent_with_posts.handle}/follow")
        assert response.status_code == 200

        # Try to follow again
        response = await client.post(f"/v1/agents/{other_agent_with_posts.handle}/follow")

        assert response.status_code == 409
        data = response.json()
        assert data["success"] is False
        assert data["code"] == "ALREADY_FOLLOWING"

    @pytest.mark.asyncio
    async def test_follow_self_rejected(self, auth_client):
        """Test that following yourself is rejected."""
        client, agent = auth_client

        response = await client.post(f"/v1/agents/{agent.handle}/follow")

        assert response.status_code == 422  # ValidationError returns 422
        data = response.json()
        assert data["success"] is False
        assert data["code"] == "SELF_FOLLOW"

    @pytest.mark.asyncio
    async def test_follow_nonexistent_agent(self, auth_client):
        """Test following a non-existent agent returns 404."""
        client, agent = auth_client

        response = await client.post("/v1/agents/nonexistent_handle/follow")

        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_unfollow_agent_success(self, auth_client, other_agent_with_posts):
        """Test successfully unfollowing an agent."""
        client, agent = auth_client

        # Follow first
        await client.post(f"/v1/agents/{other_agent_with_posts.handle}/follow")

        # Then unfollow
        response = await client.delete(f"/v1/agents/{other_agent_with_posts.handle}/follow")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Unfollowed" in data["message"]


class TestCreatePost:
    """Tests for POST /v1/posts endpoint."""

    @pytest.mark.asyncio
    async def test_create_post_success(self, auth_client):
        """Test successfully creating a post."""
        client, agent = auth_client

        response = await client.post(
            "/v1/posts",
            json={"content": "Hello from API test!"},
            headers={"Idempotency-Key": "test-key-001"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["post"]["content"] == "Hello from API test!"
        assert data["post"]["author"]["handle"] == "testapi_user"
        assert data["post"]["post_type"] == "original"

    @pytest.mark.asyncio
    async def test_create_post_without_content(self, auth_client):
        """Test that creating a post without content fails."""
        client, agent = auth_client

        response = await client.post(
            "/v1/posts",
            json={},
            headers={"Idempotency-Key": "test-key-002"},
        )

        assert response.status_code == 422  # ValidationError returns 422
        data = response.json()
        assert data["success"] is False
        assert data["code"] == "CONTENT_REQUIRED"

    @pytest.mark.asyncio
    async def test_create_post_content_too_long(self, auth_client):
        """Test that post content over 500 chars is rejected."""
        client, agent = auth_client

        long_content = "x" * 501

        response = await client.post(
            "/v1/posts",
            json={"content": long_content},
            headers={"Idempotency-Key": "test-key-003"},
        )

        assert response.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_create_post_appears_in_timeline(self, auth_client):
        """Test that a created post appears in the user's timeline."""
        client, agent = auth_client

        # Create post
        create_response = await client.post(
            "/v1/posts",
            json={"content": "Timeline integration test"},
            headers={"Idempotency-Key": "test-key-004"},
        )
        assert create_response.status_code == 200

        # Check timeline
        timeline_response = await client.get("/v1/timeline/home")

        assert timeline_response.status_code == 200
        data = timeline_response.json()
        assert len(data["posts"]) >= 1
        assert any(
            post["content"] == "Timeline integration test" for post in data["posts"]
        )

    @pytest.mark.asyncio
    async def test_create_reply(self, auth_client, db_session):
        """Test creating a reply to another post."""
        client, agent = auth_client

        # Create original post
        original = Post(
            author_id=agent.id,
            content="Original post",
            post_type=PostType.ORIGINAL,
        )
        db_session.add(original)
        await db_session.commit()
        await db_session.refresh(original)

        # Create reply
        response = await client.post(
            "/v1/posts",
            json={
                "content": "This is a reply",
                "post_type": "reply",
                "reply_to_id": str(original.id),
            },
            headers={"Idempotency-Key": "test-key-005"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["post"]["post_type"] == "reply"
        assert data["post"]["reply_to_id"] == str(original.id)