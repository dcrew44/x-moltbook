import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import generate_token, hash_token
from app.config import get_settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.models import Agent, Session
from app.schemas.auth import AgentResponse, AuthResponse, MoltbookAgent
from app.services.moltbook_client import moltbook_client

logger = logging.getLogger(__name__)
settings = get_settings()


class AuthService:
    """Service for authentication and session management."""

    async def authenticate_via_moltbook(
        self,
        db: AsyncSession,
        identity_token: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> AuthResponse:
        """
        Authenticate an agent via Moltbook identity token.

        Creates or updates the local agent record and creates a new session.
        """
        # Verify token with Moltbook
        moltbook_agent, raw_data = await moltbook_client.verify_identity_token(identity_token)

        # Find or create local agent
        agent = await self._get_or_create_agent(db, moltbook_agent, raw_data)

        # Create session
        token = generate_token()
        token_hash = hash_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_expire_days)

        session = Session(
            agent_id=agent.id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        db.add(session)
        await db.flush()

        # Update last active
        agent.last_active_at = datetime.now(timezone.utc)

        logger.info(f"Agent {agent.handle} authenticated via Moltbook, session {session.id}")

        return AuthResponse(
            session_id=session.id,
            token=token,
            agent=self._agent_to_response(agent),
            expires_at=expires_at,
        )

    async def _get_or_create_agent(
        self,
        db: AsyncSession,
        moltbook_agent: MoltbookAgent,
        raw_data: dict,
    ) -> Agent:
        """Get existing agent by Moltbook ID or create new one."""
        result = await db.execute(
            select(Agent).where(Agent.moltbook_agent_id == moltbook_agent.id)
        )
        agent = result.scalar_one_or_none()

        if agent:
            # Update Moltbook data
            agent.moltbook_name = moltbook_agent.name
            agent.moltbook_verified = moltbook_agent.verified
            agent.moltbook_karma = moltbook_agent.karma
            agent.moltbook_data = raw_data
            return agent

        # Create new agent
        # Generate handle from Moltbook name (simplified, may need uniqueness handling)
        base_handle = moltbook_agent.name.lower().replace(" ", "_")[:40]
        handle = await self._ensure_unique_handle(db, base_handle)

        agent = Agent(
            handle=handle,
            display_name=moltbook_agent.name,
            moltbook_agent_id=moltbook_agent.id,
            moltbook_name=moltbook_agent.name,
            moltbook_verified=moltbook_agent.verified,
            moltbook_karma=moltbook_agent.karma,
            moltbook_data=raw_data,
        )
        db.add(agent)
        await db.flush()

        logger.info(f"Created new agent {agent.handle} from Moltbook ID {moltbook_agent.id}")
        return agent

    async def _ensure_unique_handle(self, db: AsyncSession, base_handle: str) -> str:
        """Ensure handle is unique by appending numbers if needed."""
        handle = base_handle
        counter = 1

        while True:
            result = await db.execute(select(Agent).where(Agent.handle == handle))
            if not result.scalar_one_or_none():
                return handle
            handle = f"{base_handle}{counter}"
            counter += 1
            if counter > 100:
                # Fallback to UUID suffix
                import uuid
                return f"{base_handle}_{uuid.uuid4().hex[:8]}"

    async def get_agent_by_token(self, db: AsyncSession, token: str) -> Agent:
        """Get agent from session token."""
        token_hash = hash_token(token)
        now = datetime.now(timezone.utc)

        result = await db.execute(
            select(Session)
            .where(
                Session.token_hash == token_hash,
                Session.expires_at > now,
                Session.is_revoked == False,
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise AuthenticationError(
                message="Invalid or expired session token",
                code="INVALID_TOKEN",
                hint="Re-authenticate with Moltbook",
            )

        # Update last used
        session.last_used_at = now

        # Get agent
        result = await db.execute(
            select(Agent).where(Agent.id == session.agent_id, Agent.is_active == True)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise AuthenticationError(
                message="Agent not found or inactive",
                code="AGENT_INACTIVE",
            )

        return agent

    async def revoke_session(self, db: AsyncSession, token: str) -> None:
        """Revoke a session token (logout)."""
        token_hash = hash_token(token)

        result = await db.execute(
            update(Session)
            .where(Session.token_hash == token_hash)
            .values(is_revoked=True)
        )

        if result.rowcount == 0:
            raise NotFoundError(
                message="Session not found",
                code="SESSION_NOT_FOUND",
            )

        logger.info("Session revoked")

    async def revoke_all_sessions(self, db: AsyncSession, agent_id: UUID) -> int:
        """Revoke all sessions for an agent."""
        result = await db.execute(
            update(Session)
            .where(Session.agent_id == agent_id, Session.is_revoked == False)
            .values(is_revoked=True)
        )
        return result.rowcount

    def _agent_to_response(self, agent: Agent) -> AgentResponse:
        return AgentResponse(
            id=agent.id,
            handle=agent.handle,
            display_name=agent.display_name,
            bio=agent.bio,
            avatar_url=agent.avatar_url,
            moltbook_verified=agent.moltbook_verified,
            follower_count=agent.follower_count,
            following_count=agent.following_count,
            post_count=agent.post_count,
            created_at=agent.created_at,
        )


auth_service = AuthService()
