"""Scan lifecycle: who may be scanned, claiming a queued scan, running the
agent, and recording what the run cost."""

import itertools
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace

import anthropic
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import tracing
from .agent.matching import normalize_url
from .agent.orchestrator import AgentConfig, ScanAgent, TraceEvent
from .agent.scope import ScopedIdentifier
from .config import Settings
from .crypto import FieldCipher
from .identifiers import VERIFIABLE_KINDS
from .models import Finding, FindingSuppression, Identifier, Scan, ScanEvent, utcnow
from .openai_compat import ModelUnavailable
from .services import Services

log = logging.getLogger(__name__)


class ScopeUnavailable(Exception):
    pass


async def load_scope(
    session: AsyncSession, user_id: str, mode: str, allow_unproven_usernames: bool = False
) -> tuple[list[ScopedIdentifier], dict[str, bytes]]:
    """The ownership gate. Nothing is scanned unless the account has proven
    control of at least one email or phone. Attested names, images and context
    details ride along once that is true; usernames only once proven with a
    code in a public bio."""
    rows = [
        r
        for r in (
            await session.scalars(
                select(Identifier).where(
                    Identifier.user_id == user_id, Identifier.status.in_(("verified", "attested"))
                )
            )
        ).all()
        if r.kind != "username" or r.status == "verified" or allow_unproven_usernames
    ]
    # A proven username shows control of a profile, not of a contact point,
    # so it doesn't open the gate on its own.
    if not any(r.status == "verified" and r.kind in VERIFIABLE_KINDS for r in rows):
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
        model_id=s.resolved_model_id,
        effort=s.agent_effort,
        max_turns=s.agent_max_turns,
        max_searches=s.agent_max_searches,
        search=services.search,
        reverse_image=services.reverse_image,
        brokers=services.brokers,
        cost_of=lambda i, o, cr, cw: cost_usd(s, i, o, cr, cw),
        max_cost_usd=s.max_scan_cost_usd,
    )


def cost_usd(settings: Settings, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> float:
    """Estimated spend. Cache reads bill at 0.1x the input price and 5-minute
    cache writes at 1.25x. A model running locally costs nothing per token."""
    if settings.llm_provider == "ollama":
        return 0.0
    per_in = settings.price_input_per_mtok / 1_000_000
    per_out = settings.price_output_per_mtok / 1_000_000
    return round(input_tokens * per_in + output_tokens * per_out + cache_read * per_in * 0.1
                 + cache_write * per_in * 1.25, 6)


def scan_event(scan_id: str, seq: int, e: TraceEvent, started_ns: int) -> ScanEvent:
    """One content-free row: names, outcome codes, timings and token counts."""
    return ScanEvent(
        scan_id=scan_id,
        seq=seq,
        kind=e.kind,
        name=e.name,
        status=e.status,
        detail=e.detail[:64] if e.detail else None,
        offset_ms=max(0, (e.start_ns - started_ns) // 1_000_000),
        duration_ms=(e.end_ns - e.start_ns) // 1_000_000,
        input_tokens=e.input_tokens,
        output_tokens=e.output_tokens,
        cache_read_tokens=e.cache_read_tokens,
        cache_write_tokens=e.cache_write_tokens,
    )


def trace_writer(services: Services, scan_id: str, started_ns: int) -> Callable[[TraceEvent], Awaitable[None]]:
    """Persists each step as it finishes, in its own short transaction, so a
    scan in progress can be followed and a scan that dies keeps its trace."""
    seq = itertools.count()

    async def write(event: TraceEvent) -> None:
        async with services.sessionmaker() as session:
            session.add(scan_event(scan_id, next(seq), event, started_ns))
            await session.commit()

    return write


def record_usage(
    scan: Scan, events: Sequence[TraceEvent], settings: Settings, started_ns: int, ended_ns: int
) -> None:
    """Totals onto the scan. The per-step rows are written as they happen."""
    model = [e for e in events if e.kind == "model_call"]
    scan.model_calls = len(model)
    scan.tool_calls = len(events) - len(model)
    scan.input_tokens = sum(e.input_tokens for e in model)
    scan.output_tokens = sum(e.output_tokens for e in model)
    scan.cache_read_tokens = sum(e.cache_read_tokens for e in model)
    scan.cache_write_tokens = sum(e.cache_write_tokens for e in model)
    scan.duration_ms = (ended_ns - started_ns) // 1_000_000
    scan.cost_usd = cost_usd(
        settings, scan.input_tokens, scan.output_tokens, scan.cache_read_tokens, scan.cache_write_tokens
    )


async def claim(session: AsyncSession, scan_id: str) -> bool:
    """Move a queued scan to running. The conditional UPDATE is atomic, so when
    several workers race for one scan exactly one of them gets it."""
    result = await session.execute(
        update(Scan).where(Scan.id == scan_id, Scan.status == "queued").values(status="running", started_at=utcnow())
    )
    await session.commit()
    return result.rowcount == 1


async def run_scan(services: Services, scan_id: str) -> None:
    async with services.sessionmaker() as session:
        if not await claim(session, scan_id):
            return
        scan = await session.get(Scan, scan_id)
        settings = services.settings
        started = time.time_ns()
        agent: ScanAgent | None = None
        try:
            scoped, images = await load_scope(session, scan.user_id, scan.kind, settings.allow_unproven_usernames)
            suppressed = await load_suppressions(session, scan.user_id)
            agent = ScanAgent(
                replace(agent_config(services), on_event=trace_writer(services, scan_id, started)),
                scan.kind,
                scoped,
                images,
                is_suppressed=lambda url: suppression_key(services.cipher, url) in suppressed,
                language=scan.language,
            )
            outcome = await agent.run()
        except ScopeUnavailable as exc:
            scan.status, scan.error = "failed", str(exc)
        except (anthropic.APIError, ModelUnavailable) as exc:
            # Expired credentials, no model access in this region, network:
            # an operator problem, not something the user can retry away.
            log.error("scan %s: model call failed: %s", scan_id, type(exc).__name__)
            scan.status = "failed"
            scan.error = "The scan model could not be reached. This is a service configuration problem."
        except Exception as exc:
            # Type only: exception messages from providers can echo queries,
            # and queries contain the user's identifiers.
            log.error("scan %s failed: %s", scan_id, type(exc).__name__)
            scan.status, scan.error = "failed", "The scan failed unexpectedly. Try again later."
        else:
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

        ended = time.time_ns()
        events = agent.events if agent is not None else []
        record_usage(scan, events, settings, started, ended)
        scan.finished_at = utcnow()
        await session.commit()
        tracing.export_scan(
            scan_id=scan.id,
            kind=scan.kind,
            status=scan.status,
            provider=settings.llm_provider,
            model=settings.resolved_model_id,
            started_ns=started,
            ended_ns=ended,
            events=events,
        )
