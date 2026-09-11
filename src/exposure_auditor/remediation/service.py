from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BreachHit, Finding, Identifier, RemediationItem, User
from ..services import Services
from .plan import build_plan


async def refresh_plan(
    session: AsyncSession, services: Services, user: User, jurisdiction: str
) -> list[RemediationItem]:
    """Rebuild the plan and upsert it, keeping the status the user set on each item."""
    idents = (await session.scalars(select(Identifier).where(Identifier.user_id == user.id))).all()
    verified_emails = [(i.id, i.value) for i in idents if i.kind == "email" and i.status == "verified"]
    names = [i.value for i in idents if i.kind == "name"]

    # The same page can turn up in several scans; keep the newest finding per URL.
    latest: dict[str, Finding] = {}
    for f in (
        await session.scalars(
            select(Finding).where(Finding.user_id == user.id).order_by(Finding.created_at)
        )
    ).all():
        latest[f.url] = f
    breaches = (await session.scalars(select(BreachHit).where(BreachHit.user_id == user.id))).all()

    planned = build_plan(
        jurisdiction=jurisdiction,
        holder_name=names[0] if names else "[Your full name]",
        contact_email=verified_emails[0][1] if verified_emails else user.email,
        verified_emails=verified_emails,
        findings=list(latest.values()),
        breaches=list(breaches),
        brokers=services.brokers,
    )

    existing = {
        i.dedupe_key: i
        for i in (
            await session.scalars(select(RemediationItem).where(RemediationItem.user_id == user.id))
        ).all()
    }
    current: list[RemediationItem] = []
    for p in planned:
        item = existing.get(p.dedupe_key)
        if item is None:
            item = RemediationItem(user_id=user.id, dedupe_key=p.dedupe_key)
            session.add(item)
        item.source_type = p.source_type
        item.source_id = p.source_id
        item.action_type = p.action_type
        item.priority = p.priority
        item.title = p.title
        item.detail = p.detail
        item.url = p.url
        item.draft = p.draft
        current.append(item)
    await session.commit()
    return current
