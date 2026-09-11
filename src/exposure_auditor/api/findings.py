from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import get_services, get_session, rate_limited_user
from ..models import Finding, FindingSuppression, User
from ..scans import suppression_key
from ..schemas import FindingOut
from ..services import Services

router = APIRouter(prefix="/findings", tags=["scans"])


async def _owned(session: AsyncSession, user: User, finding_id: str) -> Finding:
    finding = await session.get(Finding, finding_id)
    if finding is None or finding.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "finding not found")
    return finding


@router.post("/{finding_id}/confirm", response_model=FindingOut)
async def confirm(
    finding_id: str,
    user: User = Depends(rate_limited_user),
    session: AsyncSession = Depends(get_session),
) -> Finding:
    """The account holder says this page is about them; it joins the action plan."""
    finding = await _owned(session, user, finding_id)
    finding.match_status = "confirmed"
    audit.record(session, user.id, "finding_confirmed", "finding", finding.id)
    await session.commit()
    return finding


@router.post("/{finding_id}/not-me", status_code=status.HTTP_204_NO_CONTENT)
async def not_me(
    finding_id: str,
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> None:
    """The page is about someone else. Delete it, since it's that person's data,
    and remember a blind index of the URL so later scans leave it out."""
    finding = await _owned(session, user, finding_id)
    key = suppression_key(services.cipher, finding.url)
    known = await session.scalar(
        select(FindingSuppression.id).where(
            FindingSuppression.user_id == user.id, FindingSuppression.url_index == key
        )
    )
    if known is None:
        session.add(FindingSuppression(user_id=user.id, url_index=key))
    # The same page may have turned up in earlier scans too.
    for other in (await session.scalars(select(Finding).where(Finding.user_id == user.id))).all():
        if suppression_key(services.cipher, other.url) == key:
            await session.delete(other)
    audit.record(session, user.id, "finding_not_me", "finding", finding_id)
    await session.commit()
