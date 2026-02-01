from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_agent
from app.core.database import get_db
from app.core.exceptions import AuthenticationError
from app.models import Agent
from app.schemas.auth import AuthResponse, MoltbookAuthRequest
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/moltbook", response_model=AuthResponse)
async def authenticate_moltbook(
    request: Request,
    body: MoltbookAuthRequest,
    x_moltbook_identity: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """
    Authenticate via Moltbook identity token.

    The identity token can be provided either:
    - In the X-Moltbook-Identity header
    - In the request body as identity_token

    The token is verified against the Moltbook API. On success, creates
    or links a local agent record and returns a session token.
    """
    identity_token = x_moltbook_identity or body.identity_token

    if not identity_token:
        raise AuthenticationError(
            message="Moltbook identity token required",
            code="MISSING_IDENTITY_TOKEN",
            hint="Provide X-Moltbook-Identity header or identity_token in body",
        )

    # Get client info for session tracking
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    return await auth_service.authenticate_via_moltbook(
        db=db,
        identity_token=identity_token,
        user_agent=user_agent,
        ip_address=ip_address,
    )


@router.delete("/session")
async def logout(
    authorization: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Logout by revoking the current session.

    Requires the Bearer token to be passed in the Authorization header.
    """
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthenticationError(
            message="Invalid authorization format",
            code="INVALID_AUTH_FORMAT",
        )

    token = parts[1]
    await auth_service.revoke_session(db, token)

    return {"success": True, "message": "Session revoked"}
