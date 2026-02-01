from typing import Any, Optional


class XMoltbookError(Exception):
    """Base exception for all X-Moltbook errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        hint: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.hint = hint
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "success": False,
            "error": self.message,
            "code": self.code,
        }
        if self.hint:
            result["hint"] = self.hint
        return result


class NotFoundError(XMoltbookError):
    """Resource not found."""

    def __init__(
        self,
        message: str = "Resource not found",
        code: str = "NOT_FOUND",
        hint: Optional[str] = None,
    ):
        super().__init__(message=message, code=code, status_code=404, hint=hint)


class AuthenticationError(XMoltbookError):
    """Authentication failed."""

    def __init__(
        self,
        message: str = "Authentication required",
        code: str = "AUTHENTICATION_REQUIRED",
        hint: Optional[str] = None,
    ):
        super().__init__(message=message, code=code, status_code=401, hint=hint)


class AuthorizationError(XMoltbookError):
    """Authorization failed."""

    def __init__(
        self,
        message: str = "Not authorized",
        code: str = "FORBIDDEN",
        hint: Optional[str] = None,
    ):
        super().__init__(message=message, code=code, status_code=403, hint=hint)


class ValidationError(XMoltbookError):
    """Validation failed."""

    def __init__(
        self,
        message: str = "Validation failed",
        code: str = "VALIDATION_ERROR",
        hint: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, status_code=422, hint=hint, details=details)


class ConflictError(XMoltbookError):
    """Resource conflict."""

    def __init__(
        self,
        message: str = "Resource already exists",
        code: str = "CONFLICT",
        hint: Optional[str] = None,
    ):
        super().__init__(message=message, code=code, status_code=409, hint=hint)


class RateLimitError(XMoltbookError):
    """Rate limit exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        code: str = "RATE_LIMIT_EXCEEDED",
        hint: Optional[str] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(message=message, code=code, status_code=429, hint=hint)
        self.retry_after = retry_after


class MoltbookError(XMoltbookError):
    """Error from Moltbook API."""

    def __init__(
        self,
        message: str = "Moltbook verification failed",
        code: str = "MOLTBOOK_ERROR",
        hint: Optional[str] = None,
    ):
        super().__init__(message=message, code=code, status_code=502, hint=hint)
