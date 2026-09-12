import hmac
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import client_rate_limit, get_current_user, get_services, get_session
from ..identifiers import InvalidIdentifier, normalize
from ..models import User, utcnow
from ..schemas import RegisterIn, ResetConfirmIn, ResetRequestIn, TokenOut
from ..security import create_access_token, hash_password, verify_password
from ..services import Services

router = APIRouter(tags=["account"])


@router.post(
    "/auth/register",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(client_rate_limit("register", 5, 3600))],
)
async def register(
    body: RegisterIn,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Same response whether or not the address is already registered: being a
    # user of a privacy tool is itself something people may not want revealed.
    email = normalize("email", body.email)
    index = services.cipher.blind_index("user-email", email)
    if await session.scalar(select(User.id).where(User.email_index == index)) is None:
        user = User(email_index=index, email=email, password_hash=hash_password(body.password))
        session.add(user)
        try:
            await session.flush()
            audit.record(session, user.id, "account_created", "user", user.id)
            await session.commit()
        except IntegrityError:
            await session.rollback()
    return {"status": "accepted", "detail": "If this email was not registered, the account now exists."}


RESET_TTL = timedelta(minutes=10)
RESET_MAX_ATTEMPTS = 5


def _reset_hash(services: Services, user_id: str, code: str) -> str:
    return services.cipher.blind_index("reset-code", f"{user_id}:{code}")


async def _account_for(session: AsyncSession, services: Services, email: str) -> User | None:
    try:
        address = normalize("email", email)
    except InvalidIdentifier:
        return None
    index = services.cipher.blind_index("user-email", address)
    return (await session.scalars(select(User).where(User.email_index == index))).first()


@router.post(
    "/auth/reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(client_rate_limit("reset", 5, 3600))],
)
async def request_password_reset(
    body: ResetRequestIn,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Send a code to the address, if it has an account.

    The answer is the same either way: whether someone uses a privacy tool is
    exactly the kind of thing this app exists to keep to themselves.
    """
    user = await _account_for(session, services, body.email)
    if user is not None:
        code = f"{secrets.randbelow(10**6):06d}"
        user.reset_code_hash = _reset_hash(services, user.id, code)
        user.reset_expires_at = utcnow() + RESET_TTL
        user.reset_attempts = 0
        audit.record(session, user.id, "password.reset_requested", "user", user.id)
        await session.commit()
        await services.sender.send("email", user.email, code)
    return {"status": "accepted", "detail": "If this email has an account, a code is on its way."}


@router.post(
    "/auth/reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(client_rate_limit("reset-confirm", 10, 3600))],
)
async def confirm_password_reset(
    body: ResetConfirmIn,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Set a new password against a code sent to the account's own address.

    Every failure says the same thing. A message that distinguished "no such
    account" from "wrong code" would answer the question the request endpoint
    refuses to answer.
    """
    refused = HTTPException(status.HTTP_400_BAD_REQUEST, "that code is not valid, or it has expired")
    user = await _account_for(session, services, body.email)
    if user is None or user.reset_code_hash is None:
        raise refused
    if user.reset_attempts >= RESET_MAX_ATTEMPTS or (
        user.reset_expires_at is None or user.reset_expires_at < utcnow()
    ):
        raise refused
    user.reset_attempts += 1
    if not hmac.compare_digest(user.reset_code_hash, _reset_hash(services, user.id, body.code)):
        await session.commit()  # keep the attempt count
        raise refused
    user.password_hash = hash_password(body.password)
    # One code, one use: a code left alive is a second way in.
    user.reset_code_hash = None
    user.reset_expires_at = None
    user.reset_attempts = 0
    audit.record(session, user.id, "password.reset", "user", user.id)
    await session.commit()


@router.post(
    "/auth/token",
    response_model=TokenOut,
    dependencies=[Depends(client_rate_limit("login", 10, 300))],
)
async def token(
    form: OAuth2PasswordRequestForm = Depends(),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    user = None
    try:
        index = services.cipher.blind_index("user-email", normalize("email", form.username))
        user = await session.scalar(select(User).where(User.email_index == index))
    except InvalidIdentifier:
        pass
    if not verify_password(user.password_hash if user else None, form.password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "incorrect email or password", headers={"WWW-Authenticate": "Bearer"}
        )
    audit.record(session, user.id, "login", "user", user.id)
    await session.commit()
    return TokenOut(access_token=create_access_token(services.settings, user.id))


@router.post("/auth/refresh", response_model=TokenOut)
async def refresh(
    user: User = Depends(get_current_user), services: Services = Depends(get_services)
) -> TokenOut:
    """Swap a still-valid token for a fresh one. The UI calls this while the
    user is active, so a session only lapses after 30 idle minutes."""
    return TokenOut(access_token=create_access_token(services.settings, user.id))


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {"id": user.id, "email": user.email, "created_at": user.created_at}


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def erase_account(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> None:
    """Erase the account and everything tied to it (identifiers, scans,
    findings, breach hits, remediation items) via ON DELETE CASCADE. Only the
    pseudonymous audit trail remains."""
    user_id = user.id
    await session.execute(delete(User).where(User.id == user_id))
    audit.record(session, user_id, "account_erased", "user", user_id)
    await session.commit()
