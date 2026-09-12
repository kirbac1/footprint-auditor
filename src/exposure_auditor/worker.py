"""The scan worker: runs queued scans outside the web process, so a deploy
or a restarted API container doesn't take a running scan with it."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select, update

from .models import Scan, utcnow
from .scans import run_scan
from .services import Services

log = logging.getLogger(__name__)

# Longer than any scan the turn and search budgets allow.
STALE_AFTER = timedelta(hours=1)


async def fail_stale_scans(services: Services) -> int:
    """Scans left 'running' by a worker that died. Nothing will finish them,
    so tell the user instead of showing a spinner forever."""
    async with services.sessionmaker() as session:
        result = await session.execute(
            update(Scan)
            .where(Scan.status == "running", Scan.started_at < utcnow() - STALE_AFTER)
            .values(
                status="failed",
                finished_at=utcnow(),
                error="The scan was interrupted before it finished. Start a new one.",
            )
        )
        await session.commit()
        return result.rowcount


async def next_queued(services: Services) -> str | None:
    async with services.sessionmaker() as session:
        return await session.scalar(
            select(Scan.id).where(Scan.status == "queued").order_by(Scan.created_at).limit(1)
        )


async def run_worker(services: Services, *, once: bool = False) -> int:
    """Run queued scans until stopped. With once=True, drain the queue and return."""
    ran = 0
    if stale := await fail_stale_scans(services):
        log.warning("marked %d interrupted scan(s) as failed", stale)
    while True:
        scan_id = await next_queued(services)
        if scan_id is not None:
            await run_scan(services, scan_id)  # a no-op if another worker claimed it first
            ran += 1
            continue
        if once:
            return ran
        await asyncio.sleep(services.settings.worker_poll_seconds)
