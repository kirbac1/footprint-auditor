import math
from collections.abc import AsyncIterator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User
from .security import decode_access_token
from .services import Services

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_services(request: Request) -> Services:
    return request.app.state.services


async def get_session(services: Services = Depends(get_services)) -> AsyncIterator[AsyncSession]:
    async with services.sessionmaker() as session:
        yield session


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        user_id = decode_access_token(services.settings, token)
    except jwt.PyJWTError:
        raise unauthorized from None
    user = await session.get(User, user_id)
    if user is None:
        raise unauthorized
    return user


def _raise_limited(retry_after: float) -> None:
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate limit exceeded",
        headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
    )


async def rate_limited_user(
    user: User = Depends(get_current_user), services: Services = Depends(get_services)
) -> User:
    retry = await services.limiter.hit(f"user:{user.id}", services.settings.rate_limit_per_minute, 60)
    if retry is not None:
        _raise_limited(retry)
    return user


def client_rate_limit(bucket: str, limit: int, window_s: int):
    """For unauthenticated endpoints (register, login), keyed by client address."""

    async def dependency(request: Request, services: Services = Depends(get_services)) -> None:
        host = request.client.host if request.client else "unknown"
        retry = await services.limiter.hit(f"{bucket}:{host}", limit, window_s)
        if retry is not None:
            _raise_limited(retry)

    return dependency
