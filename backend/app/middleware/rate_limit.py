import logging
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import get_settings
from app.core.exceptions import RateLimitError
from app.core.redis import get_redis

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""

    limit: int
    window_seconds: int
    key_prefix: str


# Rate limit configurations
RATE_LIMITS = {
    "general": RateLimitConfig(limit=100, window_seconds=60, key_prefix="rl:req"),
    "post": RateLimitConfig(limit=5, window_seconds=60, key_prefix="rl:post"),
    "post_day": RateLimitConfig(limit=100, window_seconds=86400, key_prefix="rl:post:day"),
    "like": RateLimitConfig(limit=100, window_seconds=60, key_prefix="rl:like"),
    "follow": RateLimitConfig(limit=50, window_seconds=3600, key_prefix="rl:follow"),
    "public": RateLimitConfig(limit=60, window_seconds=60, key_prefix="rl:pub"),
}


async def check_rate_limit(
    key: str,
    config: RateLimitConfig,
) -> tuple[int, int, int]:
    """
    Check rate limit using Redis sliding window.

    Returns:
        Tuple of (remaining, limit, reset_timestamp)

    Raises:
        RateLimitError if limit exceeded
    """
    try:
        redis = await get_redis()
        now = time.time()
        window_start = now - config.window_seconds

        pipe = redis.pipeline()
        # Remove old entries
        pipe.zremrangebyscore(key, "-inf", window_start)
        # Add current request
        pipe.zadd(key, {str(now): now})
        # Count requests in window
        pipe.zcard(key)
        # Set expiry
        pipe.expire(key, config.window_seconds)
        results = await pipe.execute()

        count = results[2]
        remaining = max(0, config.limit - count)
        reset_at = int(now + config.window_seconds)

        if count > config.limit:
            retry_after = config.window_seconds
            raise RateLimitError(
                message=f"Rate limit exceeded. Limit: {config.limit} per {config.window_seconds}s",
                code="RATE_LIMIT_EXCEEDED",
                hint=f"Try again in {retry_after} seconds",
                retry_after=retry_after,
            )

        return remaining, config.limit, reset_at

    except RateLimitError:
        raise
    except Exception as e:
        logger.warning(f"Rate limit check failed: {e}")
        # Fail open - allow request if Redis is down
        return config.limit, config.limit, int(time.time() + config.window_seconds)


def get_rate_limit_type(request: Request) -> Optional[str]:
    """Determine which rate limit type applies to this request."""
    path = request.url.path
    method = request.method

    # Public endpoints
    if "/public/" in path:
        return "public"

    # Post creation
    if path == "/v1/posts" and method == "POST":
        return "post"

    # Likes
    if "/like" in path and method in ("POST", "DELETE"):
        return "like"

    # Follows
    if "/follow" in path and method in ("POST", "DELETE"):
        return "follow"

    # General authenticated requests
    return "general"


def get_client_ip(request: Request) -> str:
    """
    Get the real client IP address, handling proxied requests.

    Checks X-Forwarded-For header first (for requests behind nginx/load balancer),
    falls back to direct client IP.
    """
    # Check X-Forwarded-For header (set by nginx/load balancer)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs: "client, proxy1, proxy2"
        # The first one is the original client
        return forwarded_for.split(",")[0].strip()

    # Check X-Real-IP header (alternative header some proxies use)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fall back to direct client IP
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware for rate limiting requests."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not settings.rate_limit_enabled:
            return await call_next(request)

        rate_type = get_rate_limit_type(request)
        if not rate_type:
            return await call_next(request)

        config = RATE_LIMITS.get(rate_type)
        if not config:
            return await call_next(request)

        # Determine key identifier (agent_id or IP)
        if rate_type == "public":
            identifier = get_client_ip(request)
        else:
            # For authenticated endpoints, we need the agent_id
            # This will be set by auth dependency, so we use a placeholder
            # and the actual rate limiting happens in the dependency
            # For now, we'll use IP as fallback
            identifier = get_client_ip(request)

        key = f"{config.key_prefix}:{identifier}"

        try:
            remaining, limit, reset_at = await check_rate_limit(key, config)

            response = await call_next(request)

            # Add rate limit headers
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_at)

            return response

        except RateLimitError as e:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=429,
                content=e.to_dict(),
                headers={
                    "X-RateLimit-Limit": str(config.limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(e.retry_after or config.window_seconds),
                },
            )
