from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.core.metrics import API_ERRORS_TOTAL

logger = get_logger(__name__)


class RTBException(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(RTBException):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(RTBException):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class RateLimitExceeded(RTBException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limit_exceeded"


class AuthError(RTBException):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class ForbiddenError(RTBException):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


async def rtb_exception_handler(request: Request, exc: RTBException) -> JSONResponse:
    API_ERRORS_TOTAL.labels(route=request.url.path, status_code=str(exc.status_code)).inc()
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    API_ERRORS_TOTAL.labels(route=request.url.path, status_code="500").inc()
    logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": {"code": "internal_error", "message": "An unexpected error occurred."}},
    )
