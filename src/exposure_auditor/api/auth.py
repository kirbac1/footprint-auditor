from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import client_rate_limit, get_current_user, get_services, get_session
from ..identifiers import InvalidIdentifier, normalize
from ..models import User
from ..schemas import RegisterIn, TokenOut
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
