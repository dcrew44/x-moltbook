import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import generate_token, hash_token
from app.config import get_settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.redis import RedisKeys, get_redis, jittered_ttl
from app.models import Agent, Session
from app.schemas.auth import AgentResponse, AuthResponse, DevAuthRequest, MoltbookAgent
from app.services.moltbook_client import moltbook_client

logger = logging.getLogger(__name__)
settings = get_settings()

SESSION_CACHE_BASE_TTL = 7 * 24 * 3600  # 7 days


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

        # Cache session in Redis
        await self._cache_session(token_hash, agent.id, True, expires_at)

        # Update last active
        agent.last_active_at = datetime.now(timezone.utc)

        logger.info(f"Agent {agent.handle} authenticated via Moltbook, session {session.id}")

        return AuthResponse(
            session_id=session.id,
            token=token,
            agent=self._agent_to_response(agent),
            expires_at=expires_at,
        )

    async def authenticate_dev(
        self,
        db: AsyncSession,
        request: DevAuthRequest,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> AuthResponse:
        """
        Authenticate as a dev/test user without Moltbook verification.

        Creates or retrieves the agent by handle and creates a new session.
        Only for development/testing purposes.
        """
        # Find or create agent by handle
        agent = await self._get_or_create_dev_agent(db, request)

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

        # Cache session in Redis
        await self._cache_session(token_hash, agent.id, True, expires_at)

        # Update last active
        agent.last_active_at = datetime.now(timezone.utc)

        logger.info(f"Dev agent {agent.handle} authenticated, session {session.id}")

        return AuthResponse(
            session_id=session.id,
            token=token,
            agent=self._agent_to_response(agent),
            expires_at=expires_at,
        )

    async def _get_or_create_dev_agent(
        self,
        db: AsyncSession,
        request: DevAuthRequest,
    ) -> Agent:
        """Get existing agent by handle or create new dev agent."""
        result = await db.execute(
            select(Agent).where(Agent.handle == request.handle)
        )
        agent = result.scalar_one_or_none()

        if agent:
            return agent

        # Create new dev agent
        agent = Agent(
            handle=request.handle,
            display_name=request.display_name or request.handle,
            moltbook_agent_id=None,  # No Moltbook link
            moltbook_verified=False,
        )
        db.add(agent)
        await db.flush()

        logger.info(f"Created new dev agent: {agent.handle}")
        return agent

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
        """Get agent from session token. Checks Redis cache first."""
        token_hash = hash_token(token)
        now = datetime.now(timezone.utc)

        # Try Redis cache first
        cached_session = await self._get_cached_session(token_hash)

        if cached_session:
            # Cache hit - fetch agent directly (skip Session table query)
            agent_id = UUID(cached_session["agent_id"])
            result = await db.execute(
                select(Agent).where(Agent.id == agent_id, Agent.is_active == True)
            )
            agent = result.scalar_one_or_none()

            if not agent:
                # Agent became inactive, clear cache
                await self._delete_cached_session(token_hash, agent_id)
                raise AuthenticationError(
                    message="Agent not found or inactive",
                    code="AGENT_INACTIVE",
                )

            return agent

        # Cache miss - query database
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

        # Populate cache for future requests
        await self._cache_session(token_hash, agent.id, True, session.expires_at)

        return agent

    async def revoke_session(self, db: AsyncSession, token: str) -> None:
        """Revoke a session token (logout)."""
        token_hash = hash_token(token)

        # Get agent_id before revoking (for cache cleanup)
        result = await db.execute(
            select(Session.agent_id).where(Session.token_hash == token_hash)
        )
        agent_id = result.scalar_one_or_none()

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

        # Clear cache
        await self._delete_cached_session(token_hash, agent_id)

        logger.info("Session revoked")

    async def revoke_all_sessions(self, db: AsyncSession, agent_id: UUID) -> int:
        """Revoke all sessions for an agent."""
        result = await db.execute(
            update(Session)
            .where(Session.agent_id == agent_id, Session.is_revoked == False)
            .values(is_revoked=True)
        )

        # Clear all cached sessions for this agent
        await self._delete_all_cached_sessions(agent_id)

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

    async def _cache_session(
        self,
        token_hash: str,
        agent_id: UUID,
        is_active: bool,
        expires_at: datetime,
    ) -> None:
        """Write session to Redis with TTL, track in agent_sessions Set."""
        try:
            redis = await get_redis()
            session_key = RedisKeys.session(token_hash)
            agent_sessions_key = RedisKeys.agent_sessions(str(agent_id))

            cache_data = json.dumps({
                "agent_id": str(agent_id),
                "is_active": is_active,
                "expires_at": expires_at.timestamp(),
            })

            # Calculate TTL based on expiration time
            # Handle both naive and aware datetimes
            now = datetime.now(timezone.utc)
            if expires_at.tzinfo is None:
                # Assume UTC for naive datetimes
                expires_at_aware = expires_at.replace(tzinfo=timezone.utc)
            else:
                expires_at_aware = expires_at
            ttl_seconds = int((expires_at_aware - now).total_seconds())
            if ttl_seconds > 0:
                ttl = jittered_ttl(min(ttl_seconds, SESSION_CACHE_BASE_TTL))
                await redis.set(session_key, cache_data, ex=ttl)
                await redis.sadd(agent_sessions_key, token_hash)
                # Set TTL on the set as well (slightly longer to ensure cleanup)
                await redis.expire(agent_sessions_key, ttl + 3600)
        except Exception as e:
            logger.warning(f"Failed to cache session: {e}")

    async def _get_cached_session(self, token_hash: str) -> Optional[dict]:
        """Read from Redis, validate expiration. Returns None on miss or error."""
        try:
            redis = await get_redis()
            session_key = RedisKeys.session(token_hash)
            cached = await redis.get(session_key)

            if not cached:
                return None

            data = json.loads(cached)
            expires_at = datetime.fromtimestamp(data["expires_at"], tz=timezone.utc)

            # Check if expired
            if expires_at <= datetime.now(timezone.utc):
                await redis.delete(session_key)
                return None

            # Check if active
            if not data.get("is_active", True):
                return None

            return data
        except Exception as e:
            logger.warning(f"Failed to get cached session: {e}")
            return None

    async def _delete_cached_session(self, token_hash: str, agent_id: Optional[UUID] = None) -> None:
        """Delete single session from cache."""
        try:
            redis = await get_redis()
            session_key = RedisKeys.session(token_hash)
            await redis.delete(session_key)

            if agent_id:
                agent_sessions_key = RedisKeys.agent_sessions(str(agent_id))
                await redis.srem(agent_sessions_key, token_hash)
        except Exception as e:
            logger.warning(f"Failed to delete cached session: {e}")

    async def _delete_all_cached_sessions(self, agent_id: UUID) -> None:
        """Delete all sessions for agent (for bulk logout)."""
        try:
            redis = await get_redis()
            agent_sessions_key = RedisKeys.agent_sessions(str(agent_id))

            # Get all token hashes for this agent
            token_hashes = await redis.smembers(agent_sessions_key)

            if token_hashes:
                # Delete each session cache entry
                session_keys = [RedisKeys.session(th) for th in token_hashes]
                await redis.delete(*session_keys)

            # Delete the agent sessions set
            await redis.delete(agent_sessions_key)
        except Exception as e:
            logger.warning(f"Failed to delete all cached sessions: {e}")


auth_service = AuthService()
