from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

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
