from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import get_services, get_session, rate_limited_user
from ..models import RemediationItem, User
from ..remediation.service import current_plan, refresh_plan
from ..schemas import ItemUpdateIn, RemediationItemOut, RemediationPlanOut
from ..services import Services

router = APIRouter(prefix="/remediation-plan", tags=["remediation"])

Jurisdiction = Literal["EU", "FI", "US-CA", "US", "OTHER"]


@router.get("", response_model=RemediationPlanOut)
async def get_plan(
    user: User = Depends(rate_limited_user), session: AsyncSession = Depends(get_session)
) -> RemediationPlanOut:
    """The plan as last built. Read-only: POST rebuilds it."""
    items = await current_plan(session, user)
    return RemediationPlanOut(jurisdiction=None, items=[RemediationItemOut.model_validate(i) for i in items])


@router.post("", response_model=RemediationPlanOut)
async def build_plan(
    jurisdiction: Jurisdiction = "EU",
    language: Literal["en", "fi"] = "en",
    user: User = Depends(rate_limited_user),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> RemediationPlanOut:
    """Rebuild the plan from current findings and breaches. Items are upserted
    by a stable key, so statuses the user set survive a rebuild. Item text
    follows `language`; each letter follows its recipient."""
    items = await refresh_plan(session, services, user, jurisdiction, language)
    return RemediationPlanOut(
        jurisdiction=jurisdiction, items=[RemediationItemOut.model_validate(i) for i in items]
    )


@router.patch("/items/{item_id}", response_model=RemediationItemOut)
async def update_item(
    item_id: str,
    body: ItemUpdateIn,
    user: User = Depends(rate_limited_user),
    session: AsyncSession = Depends(get_session),
) -> RemediationItem:
    item = await session.get(RemediationItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    item.status = body.status
    audit.record(session, user.id, f"remediation_{body.status}", "remediation_item", item.id)
    await session.commit()
    return item
