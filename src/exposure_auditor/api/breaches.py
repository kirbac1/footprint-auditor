from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import get_services, get_session, rate_limited_user
from ..models import BreachHit, Identifier, User, utcnow
from ..schemas import BreachCheckOut, BreachOut, PasswordRangeIn, PasswordRangeOut, RangeEntry
from ..services import Services
from ..tools.hibp import HibpError, HibpNotConfigured

router = APIRouter(prefix="/breach-check", tags=["breaches"])


@router.post("", response_model=BreachCheckOut)
async def breach_check(
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> BreachCheckOut:
    emails = (
        await session.scalars(
            select(Identifier).where(
                Identifier.user_id == user.id, Identifier.kind == "email", Identifier.status == "verified"
            )
        )
    ).all()
    if not emails:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Verify an email address first. Breach lookups send the address to Have I Been Pwned, "
            "so only addresses you have proven are yours are checked.",
        )

    hits: list[BreachHit] = []
    for ident in emails:
        try:
            breaches = await services.hibp.breaches_for_account(ident.value)
        except HibpNotConfigured:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "breach lookups are not configured") from None
        except HibpError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
        existing = {
            h.breach_name: h
            for h in (await session.scalars(select(BreachHit).where(BreachHit.identifier_id == ident.id))).all()
        }
        for b in breaches:
            hit = existing.get(b.name) or BreachHit(user_id=user.id, identifier_id=ident.id, breach_name=b.name)
            hit.title, hit.domain, hit.breach_date = b.title, b.domain, b.breach_date
            hit.data_classes, hit.is_verified, hit.checked_at = list(b.data_classes), b.is_verified, utcnow()
            session.add(hit)
            hits.append(hit)
    audit.record(session, user.id, "breach_check", None, None)
    await session.commit()
    return BreachCheckOut(
        checked_identifiers=len(emails), breaches=[BreachOut.model_validate(h) for h in hits]
    )


@router.post("/password-range", response_model=PasswordRangeOut)
async def password_range(
    body: PasswordRangeIn,
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
) -> PasswordRangeOut:
    """k-anonymity proxy to Pwned Passwords. Send the first 5 hex characters
    of SHA-1(password); compare the returned suffixes on your side."""
    prefix = body.sha1_prefix.upper()
    try:
        entries = await services.hibp.password_range(prefix)
    except HibpError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    return PasswordRangeOut(prefix=prefix, suffixes=[RangeEntry(suffix=s, count=c) for s, c in entries])
