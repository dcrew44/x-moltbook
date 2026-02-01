from typing import Annotated, Optional

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AuthenticationError
from app.core.redis import RedisKeys, get_redis
from app.models import Agent
from app.services.auth_service import auth_service


async def get_current_agent(
    request: Request,
    authorization: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> Agent:
    """
    Dependency to get the current authenticated agent.

    Extracts Bearer token from Authorization header and validates it.
    """
    if not authorization:
        raise AuthenticationError(
            message="Authorization header required",
            code="MISSING_AUTH_HEADER",
            hint="Include 'Authorization: Bearer <token>' header",
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthenticationError(
            message="Invalid authorization format",
            code="INVALID_AUTH_FORMAT",
            hint="Use 'Authorization: Bearer <token>' format",
        )

    token = parts[1]
    if not token.startswith("xmolt_"):
        raise AuthenticationError(
            message="Invalid token format",
            code="INVALID_TOKEN_FORMAT",
        )

    agent = await auth_service.get_agent_by_token(db, token)

    # Mark agent as active in Redis (for timeline fanout)
    try:
        redis = await get_redis()
        await redis.set(RedisKeys.active(str(agent.id)), "1", ex=86400)  # 24 hours
    except Exception:
        pass  # Non-critical

    return agent


async def get_optional_agent(
    request: Request,
    authorization: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> Optional[Agent]:
    """
    Dependency to optionally get the current authenticated agent.

    Returns None if no valid authentication is provided.
    """
    if not authorization:
        return None

    try:
        return await get_current_agent(request, authorization, db)
    except AuthenticationError:
        return None
