import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import get_settings
from app.core.exceptions import XMoltbookError

logger = logging.getLogger(__name__)
settings = get_settings()


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Middleware for handling exceptions and formatting error responses."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> JSONResponse:
        try:
            return await call_next(request)

        except XMoltbookError as e:
            logger.warning(f"{e.code}: {e.message}")
            return JSONResponse(
                status_code=e.status_code,
                content=e.to_dict(),
            )

        except Exception as e:
            logger.error(f"Unhandled exception: {e}")
            if settings.debug:
                logger.error(traceback.format_exc())

            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "Internal server error",
                    "code": "INTERNAL_ERROR",
                },
            )
