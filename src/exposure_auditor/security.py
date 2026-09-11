from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import Settings

_ph = PasswordHasher()
_ISSUER = "exposure-auditor"
# Verified against when the email is unknown, so a login for a non-existent
# account costs the same time as a wrong password (no account enumeration).
_DUMMY_HASH = _ph.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(settings: Settings, user_id: str) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": user_id,
        "iss": _ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> str:
    claims = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=_ISSUER,
        options={"require": ["exp", "sub", "iss"]},
    )
    return claims["sub"]
