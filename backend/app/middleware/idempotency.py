import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.database import async_session_factory
from app.models import IdempotencyKey

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL_HOURS = 24
MAX_RESPONSE_SIZE = 4096  # 4KB


def compute_request_hash(method: str, path: str, body: bytes) -> str:
    """Compute hash of request for idempotency check."""
    content = f"{method}:{path}:{body.decode('utf-8', errors='ignore')}"
    return hashlib.sha256(content.encode()).hexdigest()


async def get_idempotency_record(
    db: AsyncSession,
    key: str,
    agent_id: UUID,
) -> Optional[IdempotencyKey]:
    """Get existing idempotency record."""
    result = await db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.key == key,
            IdempotencyKey.agent_id == agent_id,
            IdempotencyKey.expires_at > datetime.now(timezone.utc),
        )
    )
    return result.scalar_one_or_none()


async def create_idempotency_record(
    db: AsyncSession,
    key: str,
    agent_id: UUID,
    request_path: str,
    request_hash: str,
    response_status: int,
    response_body: dict,
) -> IdempotencyKey:
    """Create new idempotency record."""
    # Truncate response body if too large
    body_str = json.dumps(response_body)
    if len(body_str) > MAX_RESPONSE_SIZE:
        # Store minimal response
        response_body = {
            "success": response_body.get("success"),
            "truncated": True,
        }
        if "post" in response_body:
            response_body["post_id"] = str(response_body["post"].get("id", ""))

    record = IdempotencyKey(
        key=key,
        agent_id=agent_id,
        request_path=request_path,
        request_hash=request_hash,
        response_status=response_status,
        response_body=response_body,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=IDEMPOTENCY_TTL_HOURS),
    )
    db.add(record)
    await db.commit()
    return record


async def cleanup_expired_keys(db: AsyncSession) -> int:
    """Delete expired idempotency keys."""
    result = await db.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.expires_at < datetime.now(timezone.utc)
        )
    )
    await db.commit()
    return result.rowcount


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Middleware for handling idempotent requests.

    Requires Idempotency-Key header for POST requests to certain endpoints.
    """

    IDEMPOTENT_PATHS = {"/v1/posts"}

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Only apply to POST requests on idempotent paths
        if request.method != "POST":
            return await call_next(request)

        path = request.url.path
        if path not in self.IDEMPOTENT_PATHS:
            return await call_next(request)

        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            # Allow request but log warning
            logger.warning(f"Missing Idempotency-Key for {path}")
            return await call_next(request)

        # We need agent_id from auth - this requires the auth to run first
        # For now, we'll handle this in a dependency instead
        # This middleware just validates the header format

        if len(idempotency_key) > 100:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Idempotency-Key too long (max 100 characters)",
                    "code": "INVALID_IDEMPOTENCY_KEY",
                },
            )

        return await call_next(request)
