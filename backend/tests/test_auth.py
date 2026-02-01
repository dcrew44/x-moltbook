import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.redis import RedisKeys
from app.schemas.auth import MoltbookAgent
from app.services.auth_service import auth_service


@pytest.mark.asyncio
async def test_authenticate_via_moltbook(db_session, mock_redis):
    """Test authentication via Moltbook identity token."""
    mock_agent = MoltbookAgent(
        id=str(uuid4()),
        name="Test Agent",
        karma=100,
        verified=True,
    )
    mock_raw_data = {"agent": mock_agent.model_dump()}

    with patch(
        "app.services.auth_service.moltbook_client.verify_identity_token",
        new_callable=AsyncMock,
        return_value=(mock_agent, mock_raw_data),
    ):
        with patch("app.core.redis.get_redis", return_value=mock_redis):
            result = await auth_service.authenticate_via_moltbook(
                db=db_session,
                identity_token="test-token",
                user_agent="Test Client",
                ip_address="127.0.0.1",
            )

            assert result.success is True
            assert result.token.startswith("xmolt_")
            assert result.agent.display_name == "Test Agent"
            assert result.agent.moltbook_verified is True


@pytest.mark.asyncio
async def test_get_agent_by_token(db_session, mock_redis):
    """Test getting agent by session token."""
    # First create an agent and session
    mock_agent = MoltbookAgent(
        id=str(uuid4()),
        name="Token Test Agent",
        karma=50,
        verified=False,
    )

    with patch(
        "app.services.auth_service.moltbook_client.verify_identity_token",
        new_callable=AsyncMock,
        return_value=(mock_agent, {"agent": mock_agent.model_dump()}),
    ):
        with patch("app.core.redis.get_redis", return_value=mock_redis):
            auth_result = await auth_service.authenticate_via_moltbook(
                db=db_session,
                identity_token="test-token",
            )
            await db_session.commit()

    # Now get agent by token
    agent = await auth_service.get_agent_by_token(db_session, auth_result.token)

    assert agent.display_name == "Token Test Agent"
    assert agent.handle == "token_test_agent"


@pytest.mark.asyncio
async def test_revoke_session(db_session, mock_redis):
    """Test revoking a session."""
    mock_agent = MoltbookAgent(
        id=str(uuid4()),
        name="Revoke Test",
        karma=0,
        verified=False,
    )

    with patch(
        "app.services.auth_service.moltbook_client.verify_identity_token",
        new_callable=AsyncMock,
        return_value=(mock_agent, {"agent": mock_agent.model_dump()}),
    ):
        with patch("app.core.redis.get_redis", return_value=mock_redis):
            auth_result = await auth_service.authenticate_via_moltbook(
                db=db_session,
                identity_token="test-token",
            )
            await db_session.commit()

    # Revoke session
    await auth_service.revoke_session(db_session, auth_result.token)
    await db_session.commit()

    # Should fail to get agent now
    from app.core.exceptions import AuthenticationError

    with pytest.raises(AuthenticationError):
        await auth_service.get_agent_by_token(db_session, auth_result.token)


@pytest.mark.asyncio
async def test_session_cache_hit_skips_session_query(db_session, mock_redis):
    """Test that cache hit skips Session table query."""
    mock_agent = MoltbookAgent(
        id=str(uuid4()),
        name="Cache Hit Agent",
        karma=100,
        verified=True,
    )

    # First authenticate to create agent and session
    with patch(
        "app.services.auth_service.moltbook_client.verify_identity_token",
        new_callable=AsyncMock,
        return_value=(mock_agent, {"agent": mock_agent.model_dump()}),
    ):
        with patch("app.services.auth_service.get_redis", return_value=mock_redis):
            auth_result = await auth_service.authenticate_via_moltbook(
                db=db_session,
                identity_token="test-token",
            )
            await db_session.commit()

    # Set up mock to return cached session data
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    cached_data = json.dumps({
        "agent_id": str(auth_result.agent.id),
        "is_active": True,
        "expires_at": expires_at.timestamp(),
    })
    mock_redis.get = AsyncMock(return_value=cached_data)

    # Get agent by token - should use cache
    with patch("app.services.auth_service.get_redis", return_value=mock_redis):
        agent = await auth_service.get_agent_by_token(db_session, auth_result.token)

    assert agent.display_name == "Cache Hit Agent"
    # Verify redis.get was called (cache check)
    mock_redis.get.assert_called()


@pytest.mark.asyncio
async def test_session_cache_populated_on_miss(db_session, mock_redis):
    """Test that cache is populated on cache miss."""
    mock_agent = MoltbookAgent(
        id=str(uuid4()),
        name="Cache Miss Agent",
        karma=50,
        verified=False,
    )

    # Authenticate
    with patch(
        "app.services.auth_service.moltbook_client.verify_identity_token",
        new_callable=AsyncMock,
        return_value=(mock_agent, {"agent": mock_agent.model_dump()}),
    ):
        with patch("app.services.auth_service.get_redis", return_value=mock_redis):
            auth_result = await auth_service.authenticate_via_moltbook(
                db=db_session,
                identity_token="test-token",
            )
            await db_session.commit()

    # Reset mock to simulate cache miss
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)

    # Get agent - should miss cache and then populate it
    with patch("app.services.auth_service.get_redis", return_value=mock_redis):
        agent = await auth_service.get_agent_by_token(db_session, auth_result.token)

    assert agent.display_name == "Cache Miss Agent"
    # Verify cache was populated
    mock_redis.set.assert_called()


@pytest.mark.asyncio
async def test_logout_clears_cache(db_session, mock_redis):
    """Test that logout clears the session cache."""
    mock_agent = MoltbookAgent(
        id=str(uuid4()),
        name="Logout Cache Test",
        karma=0,
        verified=False,
    )

    with patch(
        "app.services.auth_service.moltbook_client.verify_identity_token",
        new_callable=AsyncMock,
        return_value=(mock_agent, {"agent": mock_agent.model_dump()}),
    ):
        with patch("app.services.auth_service.get_redis", return_value=mock_redis):
            auth_result = await auth_service.authenticate_via_moltbook(
                db=db_session,
                identity_token="test-token",
            )
            await db_session.commit()

    # Revoke session
    with patch("app.services.auth_service.get_redis", return_value=mock_redis):
        await auth_service.revoke_session(db_session, auth_result.token)
        await db_session.commit()

    # Verify cache delete was called
    mock_redis.delete.assert_called()


@pytest.mark.asyncio
async def test_redis_down_graceful_degradation(db_session, mock_redis):
    """Test that auth still works when Redis is down."""
    mock_agent = MoltbookAgent(
        id=str(uuid4()),
        name="Redis Down Agent",
        karma=25,
        verified=True,
    )

    # Create agent and session
    with patch(
        "app.services.auth_service.moltbook_client.verify_identity_token",
        new_callable=AsyncMock,
        return_value=(mock_agent, {"agent": mock_agent.model_dump()}),
    ):
        # Simulate Redis being down during auth
        failing_redis = AsyncMock()
        failing_redis.set = AsyncMock(side_effect=Exception("Connection refused"))
        failing_redis.sadd = AsyncMock(side_effect=Exception("Connection refused"))
        failing_redis.expire = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("app.services.auth_service.get_redis", return_value=failing_redis):
            auth_result = await auth_service.authenticate_via_moltbook(
                db=db_session,
                identity_token="test-token",
            )
            await db_session.commit()

    assert auth_result.token.startswith("xmolt_")

    # Simulate Redis still down during token validation
    failing_redis.get = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("app.services.auth_service.get_redis", return_value=failing_redis):
        agent = await auth_service.get_agent_by_token(db_session, auth_result.token)

    # Should still work via DB fallback
    assert agent.display_name == "Redis Down Agent"
