from __future__ import annotations

from collections.abc import AsyncGenerator

import redis.asyncio as redis
from fastapi import Depends, Header, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.exceptions import AuthError, RateLimitExceeded
from app.core.rate_limit import is_allowed
from app.core.redis_client import get_redis
from app.core.security import decode_access_token

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login", auto_error=False)


async def get_redis_dep() -> AsyncGenerator[redis.Redis, None]:
    client = get_redis()
    try:
        yield client
    finally:
        await client.aclose()


async def get_current_user(token: str | None = Depends(oauth2_scheme)) -> dict:
    if token is None:
        raise AuthError("Missing bearer token")
    payload = decode_access_token(token)
    if payload is None:
        raise AuthError("Invalid or expired token")
    return payload


def require_role(*roles: str):
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise AuthError(f"Role {user.get('role')} not permitted; requires one of {roles}")
        return user

    return _check


_LIMITS = {
    "PUBLISHER": settings.RATE_LIMIT_PUBLISHER_PER_MIN,
    "ADMIN": settings.RATE_LIMIT_ADMIN_PER_MIN,
    "DSP": settings.RATE_LIMIT_DSP_PER_MIN,
}


async def enforce_rate_limit(
    request: Request,
    redis_client: redis.Redis = Depends(get_redis_dep),
    x_client_role: str = Header(default="PUBLISHER"),
    x_client_id: str = Header(default="anonymous"),
) -> None:
    """Redis sliding-window rate limiting keyed by role + client id header.
    In production the role/id would come from the authenticated principal;
    headers are used here so the limiter is exercisable without requiring a
    full auth flow for every load-test/demo request."""
    limit = _LIMITS.get(x_client_role.upper(), settings.RATE_LIMIT_PUBLISHER_PER_MIN)
    allowed = await is_allowed(redis_client, x_client_role.upper(), x_client_id, limit)
    if not allowed:
        raise RateLimitExceeded(f"Rate limit exceeded for role={x_client_role}, limit={limit}/min")
