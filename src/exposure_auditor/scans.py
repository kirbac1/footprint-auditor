"""Scan lifecycle: who may be scanned, and running the agent in the background."""

import logging

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .agent.matching import normalize_url
from .agent.orchestrator import AgentConfig, ScanAgent
from .agent.scope import ScopedIdentifier
from .crypto import FieldCipher
from .models import Finding, FindingSuppression, Identifier, Scan, utcnow
from .services import Services

log = logging.getLogger(__name__)


class ScopeUnavailable(Exception):
    pass


async def load_scope(
    session: AsyncSession, user_id: str, mode: str
) -> tuple[list[ScopedIdentifier], dict[str, bytes]]:
    """The ownership gate. Nothing is scanned unless the account has proven
    control of at least one email or phone; attested names, usernames, images
    and context details only ride along once that is true."""
    rows = (
        await session.scalars(
            select(Identifier).where(
                Identifier.user_id == user_id, Identifier.status.in_(("verified", "attested"))
            )
        )
    ).all()
    if not any(r.status == "verified" for r in rows):
        raise ScopeUnavailable(
            "Verify at least one email address or phone number before scanning. Scans only cover "
            "identifiers tied to an account that has proven it controls a contact point."
        )
    if mode == "impersonation" and not any(r.kind in {"name", "username", "image"} for r in rows):
        raise ScopeUnavailable("An impersonation check needs a name, username or photo in scope.")
    scoped = [ScopedIdentifier(id=r.id, kind=r.kind, value=r.value) for r in rows]
    images = {r.id: r.image_data for r in rows if r.kind == "image" and r.image_data}
    return scoped, images


def suppression_key(cipher: FieldCipher, url: str) -> str:
    """Blind index of a page the account holder said is not about them."""
    return cipher.blind_index("suppressed-url", normalize_url(url))


async def load_suppressions(session: AsyncSession, user_id: str) -> set[str]:
    rows = await session.scalars(
        select(FindingSuppression.url_index).where(FindingSuppression.user_id == user_id)
    )
    return set(rows.all())


def agent_config(services: Services) -> AgentConfig:
    s = services.settings
    return AgentConfig(
        llm=services.llm,
        model_id=s.model_id,
        effort=s.agent_effort,
        max_turns=s.agent_max_turns,
        max_searches=s.agent_max_searches,
        search=services.search,
        reverse_image=services.reverse_image,
        brokers=services.brokers,
    )


async def run_scan(services: Services, scan_id: str) -> None:
    async with services.sessionmaker() as session:
        scan = await session.get(Scan, scan_id)
        if scan is None or scan.status != "queued":
            return
        scan.status = "running"
        scan.started_at = utcnow()
        await session.commit()

        try:
            scoped, images = await load_scope(session, scan.user_id, scan.kind)
            suppressed = await load_suppressions(session, scan.user_id)
            agent = ScanAgent(
                agent_config(services),
                scan.kind,
                scoped,
                images,
                is_suppressed=lambda url: suppression_key(services.cipher, url) in suppressed,
            )
            outcome = await agent.run()
        except ScopeUnavailable as exc:
            scan.status, scan.error, scan.finished_at = "failed", str(exc), utcnow()
            await session.commit()
            return
        except anthropic.APIError as exc:
            # Expired credentials, no model access in this region, network:
            # an operator problem, not something the user can retry away.
            log.error("scan %s: model call failed: %s", scan_id, type(exc).__name__)
            scan.status, scan.finished_at = "failed", utcnow()
            scan.error = "The scan model could not be reached. This is a service configuration problem."
            await session.commit()
            return
        except Exception as exc:
            # Type only: exception messages from providers can echo queries,
            # and queries contain the user's identifiers.
            log.error("scan %s failed: %s", scan_id, type(exc).__name__)
            scan.status, scan.finished_at = "failed", utcnow()
            scan.error = "The scan failed unexpectedly. Try again later."
            await session.commit()
            return

        for f in outcome.findings:
            session.add(
                Finding(
                    scan_id=scan.id,
                    user_id=scan.user_id,
                    category=f.category,
                    url=f.url,
                    title=f.title,
                    broker_id=f.broker_id,
                    matched_identifier_ids=f.matched_identifier_ids,
                    confidence=f.confidence,
                    rationale=f.rationale,
                    match_status=f.match_status,
                )
            )
        scan.status = "refused" if outcome.status == "refused" else "completed"
        scan.summary = outcome.summary or None
        scan.namesakes_excluded = outcome.namesakes_excluded
        scan.finished_at = utcnow()
        await session.commit()
